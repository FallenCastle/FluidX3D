#pragma once

// Per-instance DDF storage. Arithmetic remains FP32 in both modes.
enum class DdfStorage { Float16Scaled, Float32 };
constexpr unsigned ddf_storage_bytes(DdfStorage storage) { return storage == DdfStorage::Float16Scaled ? 2u : 4u; }
constexpr const char *ddf_storage_name(DdfStorage storage) {
    return storage == DdfStorage::Float16Scaled ? "FP16S" : "FP32";
}
