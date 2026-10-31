#include <cstdio>

__attribute__((noinline)) void write_balance(volatile int* balance) {
    *balance = 42;
}

int main() {
    std::puts("Writing through an invalid balance pointer");
    std::fflush(stdout);
    write_balance(nullptr);
}
