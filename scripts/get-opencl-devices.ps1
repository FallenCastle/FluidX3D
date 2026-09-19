#Requires -Version 5.1
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT -or ![Environment]::Is64BitProcess) {
    throw 'Run this probe in 64-bit Windows PowerShell on NUC.'
}

# Keep the platform/device order used by src/opencl.hpp::get_devices().
if (-not ('FluidX3D.NucOpenCLProbe' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;

namespace FluidX3D {
    public class OpenCLDeviceRecord {
        public int id { get; set; }
        public string platform { get; set; }
        public string name { get; set; }
        public string vendor { get; set; }
        public string driver { get; set; }
        public string version { get; set; }
    }

    public static class NucOpenCLProbe {
        [DllImport("OpenCL.dll")]
        static extern int clGetPlatformIDs(uint n, [Out] IntPtr[] platforms, out uint count);
        [DllImport("OpenCL.dll")]
        static extern int clGetPlatformInfo(IntPtr platform, uint param, UIntPtr size, StringBuilder value, out UIntPtr length);
        [DllImport("OpenCL.dll")]
        static extern int clGetDeviceIDs(IntPtr platform, ulong type, uint n, [Out] IntPtr[] devices, out uint count);
        [DllImport("OpenCL.dll")]
        static extern int clGetDeviceInfo(IntPtr device, uint param, UIntPtr size, StringBuilder value, out UIntPtr length);

        static void Check(int code, string operation) {
            if (code != 0) throw new InvalidOperationException(operation + " failed: OpenCL status " + code);
        }

        static string ReadText(IntPtr handle, uint param, bool platform) {
            var text = new StringBuilder(4096);
            UIntPtr length;
            int code = platform
                ? clGetPlatformInfo(handle, param, new UIntPtr(4096), text, out length)
                : clGetDeviceInfo(handle, param, new UIntPtr(4096), text, out length);
            Check(code, "Read OpenCL device information");
            return text.ToString();
        }

        public static OpenCLDeviceRecord[] GetDevices() {
            uint count;
            Check(clGetPlatformIDs(0, null, out count), "Enumerate OpenCL platforms");
            var results = new List<OpenCLDeviceRecord>();
            if (count == 0) return results.ToArray();
            var platforms = new IntPtr[count];
            Check(clGetPlatformIDs(count, platforms, out count), "Read OpenCL platforms");
            foreach (var platform in platforms) {
                uint deviceCount;
                int status = clGetDeviceIDs(platform, 0xFFFFFFFFUL, 0, null, out deviceCount);
                if (status == -1) continue; // CL_DEVICE_NOT_FOUND
                Check(status, "Enumerate OpenCL devices");
                if (deviceCount == 0) continue;
                var devices = new IntPtr[deviceCount];
                Check(clGetDeviceIDs(platform, 0xFFFFFFFFUL, deviceCount, devices, out deviceCount), "Read OpenCL devices");
                foreach (var device in devices) {
                    results.Add(new OpenCLDeviceRecord {
                        id = results.Count,
                        platform = ReadText(platform, 0x0902, true),
                        name = ReadText(device, 0x102B, false),
                        vendor = ReadText(device, 0x102C, false),
                        driver = ReadText(device, 0x102D, false),
                        version = ReadText(device, 0x102F, false)
                    });
                }
            }
            return results.ToArray();
        }
    }
}
'@
}

ConvertTo-Json -InputObject @([FluidX3D.NucOpenCLProbe]::GetDevices()) -Depth 4
