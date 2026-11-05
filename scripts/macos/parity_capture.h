// SPDX-FileCopyrightText: 2026 MontroneDSP
// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cstdlib>
#include <cfenv>
#include <cstdio>
#include <filesystem>
#include <fstream>
#include <stdexcept>
#include <string>
#include <vector>
namespace swaraxt_capture {
inline void floatingContext() {
    unsigned long long control = 0;
#if defined(__aarch64__)
    __asm__ volatile("mrs %0, fpcr" : "=r"(control));
#elif defined(__x86_64__)
    unsigned int mxcsr = 0;
    __asm__ volatile("stmxcsr %0" : "=m"(mxcsr));
    control = mxcsr;
#endif
    std::printf("CAPTURE_FP rounding=%d architecture_control=%llu\n", std::fegetround(), control);
}
inline void write(const std::string& name, const std::vector<float>& samples) {
    const char* root = std::getenv("SWARA_CURRENT_REFERENCE_DIR");
    if (root == nullptr) throw std::runtime_error("Diagnostic capture directory required");
    const auto path = std::filesystem::path(root) / (name + ".f32");
    std::ofstream out(path, std::ios::binary);
    out.write(reinterpret_cast<const char*>(samples.data()), static_cast<std::streamsize>(samples.size()*sizeof(float)));
    out.flush();
    if (!out.good()) throw std::runtime_error("Incomplete diagnostic capture");
}
} // namespace swaraxt_capture
