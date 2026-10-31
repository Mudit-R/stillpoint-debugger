#include <cstdio>

__attribute__((noinline)) int divide(int numerator, int denominator) {
    return numerator / denominator;
}

int main() {
    volatile int denominator = 0;
    std::puts("Dividing by zero");
    std::fflush(stdout);
    return divide(42, denominator);
}
