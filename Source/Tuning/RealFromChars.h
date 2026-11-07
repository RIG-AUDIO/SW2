// Copyright 2026 MontroneDSP.
// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <charconv>
#include <system_error>

#if defined(__APPLE__) || defined(SWARAXT_FORCE_PORTABLE_REAL_PARSER)
#include <type_traits>
#include <utility>
#include "../../third_party/fast_float/include/fast_float/fast_float.h"
#endif

namespace swaraxt::tuning::detail {
#if defined(__APPLE__) || defined(SWARAXT_FORCE_PORTABLE_REAL_PARSER)
template <typename T, typename = void> struct HasStdRealFromChars : std::false_type {};
template <typename T> struct HasStdRealFromChars<T, std::void_t<decltype(
    std::from_chars(std::declval<const char*>(), std::declval<const char*>(),
                    std::declval<T&>(), std::chars_format::general))>> : std::true_type {};

template <typename T = double>
inline std::from_chars_result realFromChars(const char* first, const char* last, T& value) noexcept
{
#if defined(SWARAXT_FORCE_PORTABLE_REAL_PARSER)
    constexpr bool useStandard = false; // Independent regression builds only.
#else
    constexpr bool useStandard = HasStdRealFromChars<T>::value;
#endif
    if constexpr (useStandard)
        return std::from_chars(first, last, value, std::chars_format::general);
    else
    {
        // std::from_chars leaves the destination unchanged on range errors.
        // fast_float may write zero/infinity on range errors, so commit only success.
        T parsedValue {};
        const auto result = fast_float::from_chars(first, last, parsedValue, fast_float::chars_format::general);
        if (result.ec == std::errc())
            value = parsedValue;
        return {result.ptr, result.ec};
    }
}
#else
inline std::from_chars_result realFromChars(const char* first, const char* last, double& value) noexcept
{
    return std::from_chars(first, last, value, std::chars_format::general);
}
#endif
} // namespace swaraxt::tuning::detail
