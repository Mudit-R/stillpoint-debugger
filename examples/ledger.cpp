#include <cstdio>

__attribute__((noinline)) int apply_fee(int balance, int fee) {
    int remaining = balance - fee;
    return remaining;
}

__attribute__((noinline)) int settle(int balance) {
    int fee = 24;
    int net = apply_fee(balance, fee);
    return net;
}

int main() {
    int balance = 1000;
    std::printf("Opening balance: %d\n", balance);
    int net = settle(balance);
    std::printf("Settlement: %d\n", net);
    return net == 976 ? 0 : 1;
}
