// Stillpoint's tracer runs on one OS thread. ptrace ownership stays here.
#include <sys/ptrace.h>
#include <sys/user.h>
#include <sys/wait.h>
#include <unistd.h>
#include <elf.h>
#include <fcntl.h>
#include <signal.h>
#include <cerrno>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

using Address = unsigned long long;
std::string quote(const std::string& s) {
    std::ostringstream out; out << '"';
    for (unsigned char c : s) {
        if (c == '"' || c == '\\') out << '\\' << c;
        else if (c < 32) out << "\\u" << std::hex << std::setw(4) << std::setfill('0') << int(c);
        else out << c;
    }
    return out.str() + '"';
}
std::string hex(Address n) { std::ostringstream s; s << "0x" << std::hex << n; return s.str(); }
long trace(enum __ptrace_request req, pid_t pid, Address addr = 0, Address data = 0) {
    errno = 0;
    long result = ptrace(req, pid, reinterpret_cast<void*>(addr), reinterpret_cast<void*>(data));
    if (result == -1 && errno) throw std::runtime_error(std::strerror(errno));
    return result;
}
struct Breakpoint { unsigned char original; bool enabled; };
class Debugger {
    pid_t pid = -1;
    std::string state = "idle", reason = "No process", output;
    std::map<Address, Breakpoint> breaks;
    std::map<std::string, Address> symbols;
    Address pending = 0;
    int pending_signal = 0;
    FILE* capture = nullptr;

    void require_stop() const {
        if (state != "stopped") throw std::runtime_error("The process must be stopped first");
    }
    user_regs_struct regs() {
        user_regs_struct r{}; trace(PTRACE_GETREGS, pid, 0, reinterpret_cast<Address>(&r)); return r;
    }
    void byte(Address addr, unsigned char value) {
        Address aligned = addr & ~Address(sizeof(long)-1);
        unsigned shift = (addr-aligned)*8;
        auto word = static_cast<unsigned long>(trace(PTRACE_PEEKDATA, pid, aligned));
        word = (word & ~(0xffUL << shift)) | (static_cast<unsigned long>(value) << shift);
        trace(PTRACE_POKEDATA, pid, aligned, word);
    }
    void collect_output() {
        if (!capture) return;
        // pread does not move the child's shared file offset.
        char buf[4096];
        while (output.size() < 65536) {
            auto n = pread(fileno(capture), buf, sizeof(buf), static_cast<off_t>(output.size()));
            if (n <= 0) break;
            output.append(buf, static_cast<size_t>(n));
        }
    }
    void load_symbols(const std::string& path) {
        std::ifstream input(path, std::ios::binary);
        if (!input) throw std::runtime_error("Cannot open executable");
        input.seekg(0, std::ios::end); auto size = input.tellg(); input.seekg(0);
        if (size < static_cast<std::streamoff>(sizeof(Elf64_Ehdr)) || size > 64*1024*1024)
            throw std::runtime_error("Executable size is unsupported");
        std::vector<char> bytes(static_cast<size_t>(size)); input.read(bytes.data(), size);
        auto range = [&](Address offset, Address count) {
            if (offset > bytes.size() || count > bytes.size()-offset) throw std::runtime_error("Invalid ELF range");
        };
        Elf64_Ehdr header{}; std::memcpy(&header, bytes.data(), sizeof(header));
        if (std::memcmp(header.e_ident, ELFMAG, SELFMAG) || header.e_ident[EI_CLASS] != ELFCLASS64 ||
            header.e_ident[EI_DATA] != ELFDATA2LSB || header.e_machine != EM_X86_64 || header.e_type != ET_EXEC)
            throw std::runtime_error("Use a Linux x86-64 non-PIE executable (-g -O0 -fno-omit-frame-pointer -no-pie)");
        if (header.e_shentsize != sizeof(Elf64_Shdr)) throw std::runtime_error("Unsupported ELF section table");
        range(header.e_shoff, Address(header.e_shnum)*sizeof(Elf64_Shdr));
        std::vector<Elf64_Shdr> sections(header.e_shnum);
        std::memcpy(sections.data(), bytes.data()+header.e_shoff, sections.size()*sizeof(Elf64_Shdr));
        symbols.clear();
        for (const auto& section : sections) {
            if (section.sh_type != SHT_SYMTAB) continue;
            if (section.sh_link >= sections.size() || section.sh_entsize != sizeof(Elf64_Sym))
                throw std::runtime_error("Invalid symbol table");
            const auto& strings = sections[section.sh_link];
            range(section.sh_offset, section.sh_size); range(strings.sh_offset, strings.sh_size);
            for (Address i=0; i+sizeof(Elf64_Sym)<=section.sh_size; i+=sizeof(Elf64_Sym)) {
                Elf64_Sym sym{}; std::memcpy(&sym, bytes.data()+section.sh_offset+i, sizeof(sym));
                if (ELF64_ST_TYPE(sym.st_info) != STT_FUNC || !sym.st_value || sym.st_name >= strings.sh_size) continue;
                const char* name = bytes.data()+strings.sh_offset+sym.st_name;
                if (!std::memchr(name, 0, strings.sh_size-sym.st_name)) throw std::runtime_error("Invalid symbol name");
                symbols[name] = sym.st_value;
            }
        }
    }
    bool wait_event(bool bounded = true) {
        auto deadline = std::chrono::steady_clock::now()+std::chrono::milliseconds(bounded ? 700 : 0);
        do {
            int status = 0;
            auto result = waitpid(pid, &status, WNOHANG);
            if (result == -1) { if (errno == EINTR) continue; throw std::runtime_error("waitpid failed"); }
            if (result == 0) {
                if (!bounded || std::chrono::steady_clock::now() >= deadline) return false;
                std::this_thread::sleep_for(std::chrono::milliseconds(2)); continue;
            }
            if (WIFEXITED(status) || WIFSIGNALED(status)) {
                state = "exited";
                reason = WIFEXITED(status) ? "Exited with code " + std::to_string(WEXITSTATUS(status)) : "Terminated by signal " + std::to_string(WTERMSIG(status));
                pid = -1; pending = 0; pending_signal = 0; return true;
            }
            if (!WIFSTOPPED(status)) continue;
            state = "stopped"; int sig = WSTOPSIG(status); pending_signal = 0;
            reason = "Stopped by signal " + std::to_string(sig);
            auto r = regs();
            auto found = breaks.find(r.rip-1);
            if (sig == SIGTRAP && found != breaks.end() && found->second.enabled) {
                pending = r.rip-1; byte(pending, found->second.original); found->second.enabled = false;
                r.rip = pending; trace(PTRACE_SETREGS, pid, 0, reinterpret_cast<Address>(&r));
                reason = "Breakpoint at " + hex(pending);
            } else if (sig == SIGTRAP) {
                siginfo_t info{}; trace(PTRACE_GETSIGINFO, pid, 0, reinterpret_cast<Address>(&info));
                if (info.si_code == TRAP_TRACE) reason = "Instruction step";
                else pending_signal = sig;
            } else if (sig != SIGSTOP) pending_signal = sig;
            return true;
        } while (true);
    }
    void resume(bool single) {
        require_stop();
        if (pending) {
            auto addr = pending; pending = 0;
            trace(PTRACE_SINGLESTEP, pid); state = "running";
            if (!wait_event()) throw std::runtime_error("Breakpoint step is still running; poll before continuing");
            if (state == "exited") return;
            if (breaks.contains(addr)) { byte(addr, 0xcc); breaks[addr].enabled = true; }
            if (single || pending_signal || pending) return;
        }
        int sig = pending_signal; pending_signal = 0;
        trace(single ? PTRACE_SINGLESTEP : PTRACE_CONT, pid, 0, sig);
        state = "running"; reason = "Running"; wait_event();
    }
public:
    ~Debugger() { stop(); if (capture) fclose(capture); }
    void stop() {
        if (pid > 0) { kill(pid, SIGKILL); int status; while (waitpid(pid, &status, 0)<0 && errno==EINTR) {} }
        pid=-1; state="idle"; reason="Session ended"; pending=0; pending_signal=0; breaks.clear();
    }
    Address resolve(const std::string& value) {
        if (symbols.contains(value)) return symbols[value];
        size_t consumed=0; Address addr=std::stoull(value, &consumed, 0);
        if (consumed != value.size()) throw std::runtime_error("Unknown symbol or address");
        return addr;
    }
    void command(const std::string& line) {
        std::istringstream in(line); std::string cmd, arg; in >> cmd; std::getline(in >> std::ws, arg);
        if (cmd == "launch") {
            stop(); load_symbols(arg); output.clear();
            if (capture) fclose(capture);
            capture = tmpfile(); if (!capture) throw std::runtime_error("Cannot create output capture");
            pid = fork();
            if (pid == -1) throw std::runtime_error("fork failed");
            if (pid == 0) {
                int null_input = open("/dev/null", O_RDONLY);
                if (null_input < 0 || dup2(null_input, STDIN_FILENO) == -1) _exit(126);
                if (null_input > STDERR_FILENO) close(null_input);
                dup2(fileno(capture), STDOUT_FILENO); dup2(fileno(capture), STDERR_FILENO);
                if (fileno(capture) > STDERR_FILENO) close(fileno(capture));
                if (ptrace(PTRACE_TRACEME,0,nullptr,nullptr) == -1) _exit(126);
                execl(arg.c_str(), arg.c_str(), static_cast<char*>(nullptr)); _exit(127);
            }
            state="running"; wait_event();
            if (state != "stopped") throw std::runtime_error("Executable did not stop at exec");
            trace(PTRACE_SETOPTIONS, pid, 0, PTRACE_O_EXITKILL);
            pending_signal=0; reason="Executable loaded";
        } else if (cmd=="break") {
            require_stop(); auto addr=resolve(arg);
            if (!breaks.contains(addr)) { auto word=trace(PTRACE_PEEKDATA,pid,addr); breaks[addr]={static_cast<unsigned char>(word & 0xff),true}; byte(addr,0xcc); }
        } else if (cmd=="delete") {
            require_stop(); auto addr=resolve(arg);
            if (!breaks.contains(addr)) throw std::runtime_error("Breakpoint does not exist");
            if (breaks[addr].enabled) byte(addr,breaks[addr].original);
            breaks.erase(addr); // pending still needs to step the restored instruction
        } else if (cmd=="continue") resume(false);
        else if (cmd=="step") resume(true);
        else if (cmd=="pause") { if (state!="running") throw std::runtime_error("Process is not running"); kill(pid,SIGSTOP); wait_event(); }
        else if (cmd=="poll") { if (state=="running") wait_event(false); }
        else if (cmd=="stop") stop();
        else if (cmd!="status") throw std::runtime_error("Unknown command");
    }
    std::string snapshot(const std::string& error="") {
        collect_output(); std::ostringstream s;
        s << "{\"state\":" << quote(state) << ",\"reason\":" << quote(reason) << ",\"error\":" << quote(error)
          << ",\"pid\":" << pid << ",\"output\":" << quote(output) << ",\"registers\":{";
        if (state=="stopped") {
            auto r=regs();
            s << "\"rip\":" << quote(hex(r.rip)) << ",\"rsp\":" << quote(hex(r.rsp)) << ",\"rbp\":" << quote(hex(r.rbp))
              << ",\"rax\":" << quote(hex(r.rax)) << ",\"rbx\":" << quote(hex(r.rbx)) << ",\"rcx\":" << quote(hex(r.rcx))
              << ",\"rdx\":" << quote(hex(r.rdx)) << ",\"rsi\":" << quote(hex(r.rsi)) << ",\"rdi\":" << quote(hex(r.rdi))
              << ",\"r8\":" << quote(hex(r.r8)) << ",\"r9\":" << quote(hex(r.r9)) << ",\"eflags\":" << quote(hex(r.eflags));
        }
        s << "},\"breakpoints\":["; bool first=true;
        for (auto [addr,bp]:breaks) { if(!first)s<<','; first=false; s << quote(hex(addr)); (void)bp; }
        s << "],\"symbols\":["; first=true;
        for (auto [name,addr]:symbols) { if(!first)s<<','; first=false; s << "{\"name\":" << quote(name) << ",\"address\":" << quote(hex(addr)) << '}'; }
        s << "],\"frames\":[";
        if (state=="stopped") {
            auto r=regs(); Address pc=r.rip, frame=r.rbp;
            for (int i=0;i<24;i++) {
                if(i)s<<',';
                s << quote(hex(pc));
                if (!frame || frame%8) break;
                try {
                    auto next=static_cast<Address>(trace(PTRACE_PEEKDATA,pid,frame));
                    pc=static_cast<Address>(trace(PTRACE_PEEKDATA,pid,frame+8));
                    if(next<=frame || next-frame>1024*1024 || !pc)break;
                    frame=next;
                } catch (...) { break; }
            }
        }
        s << "],\"memory\":[";
        if(state=="stopped") {
            auto r=regs();
            for(int i=0;i<8;i++) {
                try {
                    auto value=static_cast<Address>(trace(PTRACE_PEEKDATA,pid,r.rsp+i*8));
                    if(i)s<<',';
                    s << "{\"address\":" << quote(hex(r.rsp+i*8)) << ",\"value\":" << quote(hex(value)) << '}';
                } catch (...) { break; }
            }
        }
        return s.str()+"]}";
    }
};
int main() {
    Debugger debugger; std::string line;
    while (std::getline(std::cin,line)) {
        std::string error;
        try { debugger.command(line); } catch(const std::exception& e) { error=e.what(); }
        try { std::cout << debugger.snapshot(error) << std::endl; }
        catch(const std::exception& e) { std::cout << "{\"error\":" << quote(e.what()) << "}" << std::endl; }
    }
}
