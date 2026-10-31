#include <cstdio>
#include <sys/mman.h>
#include <unistd.h>

int main() {
    const long page_size = sysconf(_SC_PAGESIZE);
    void* guard = mmap(nullptr, static_cast<size_t>(page_size), PROT_NONE,
                       MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (guard == MAP_FAILED) return 2;
    std::printf("Reading protected address %p\n", guard);
    std::fflush(stdout);
    return *static_cast<volatile int*>(guard);
}
