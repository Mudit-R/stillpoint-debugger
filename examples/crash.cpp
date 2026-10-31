#include <cstdio>

__attribute__((noinline)) int read_balance(volatile int* balance) {
    return *balance;
}

int main() {
    std::puts("About to read an invalid balance pointer");
    std::fflush(stdout);
    return read_balance(nullptr);
}
