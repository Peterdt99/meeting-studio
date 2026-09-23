using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
using System.Text;

namespace MeetingStudioDesktop
{
    public static class ShortcutInstaller
    {
        public static void Install(string exePath, string appId)
        {
            if (String.IsNullOrWhiteSpace(exePath))
                throw new ArgumentException("An application path is required.", "exePath");
            if (String.IsNullOrWhiteSpace(appId))
                throw new ArgumentException("An application identity is required.", "appId");

            exePath = Path.GetFullPath(exePath);
            if (!File.Exists(exePath))
                throw new FileNotFoundException("Meeting Studio could not be found.", exePath);

            string[] folders = new string[] {
                Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory),
                Environment.GetFolderPath(Environment.SpecialFolder.Programs)
            };
            HashSet<string> installed = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (string folder in folders)
            {
                if (String.IsNullOrWhiteSpace(folder))
                    throw new IOException("Windows could not locate the desktop or Start menu folder.");
                string destination = Path.Combine(folder, "Meeting Studio.lnk");
                if (installed.Add(destination))
                {
                    Directory.CreateDirectory(folder);
                    SaveShortcut(destination, exePath, appId);
                }
            }
        }

        private static void SaveShortcut(string destination, string exePath, string appId)
        {
            string temporaryPath = Path.Combine(Path.GetDirectoryName(destination),
                ".MeetingStudio-" + Guid.NewGuid().ToString("N") + ".lnk");
            object shortcut = null;
            try
            {
                shortcut = new ShellLink();
                IShellLinkW link = (IShellLinkW)shortcut;
                link.SetPath(exePath);
                link.SetArguments("");
                link.SetWorkingDirectory(Path.GetDirectoryName(exePath));
                link.SetDescription("Local recordings, speaker transcripts, and meeting notes");
                string iconPath = Path.Combine(Path.GetDirectoryName(exePath), "Meeting Studio.ico");
                link.SetIconLocation(File.Exists(iconPath) ? iconPath : exePath, 0);
                link.SetShowCmd(1);

                IPropertyStore properties = (IPropertyStore)shortcut;
                PROPERTYKEY identityKey = new PROPERTYKEY(
                    new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), 5);
                PROPVARIANT value = PROPVARIANT.FromString(appId);
                try
                {
                    Marshal.ThrowExceptionForHR(properties.SetValue(ref identityKey, ref value));
                    Marshal.ThrowExceptionForHR(properties.Commit());
                }
                finally
                {
                    PropVariantClear(ref value);
                }

                ((IPersistFile)shortcut).Save(temporaryPath, true);
                // Keep an existing shortcut intact until the new one is fully written.
                if (File.Exists(destination))
                    File.Replace(temporaryPath, destination, null);
                else
                    File.Move(temporaryPath, destination);
                SHChangeNotify(0x00002000, 0x0005, destination, IntPtr.Zero);
            }
            finally
            {
                if (shortcut != null && Marshal.IsComObject(shortcut))
                    Marshal.FinalReleaseComObject(shortcut);
                if (File.Exists(temporaryPath))
                {
                    try { File.Delete(temporaryPath); }
                    catch (IOException) { }
                    catch (UnauthorizedAccessException) { }
                }
            }
        }

        internal static void SetWindowIdentity(IntPtr window, string exePath, string appId)
        {
            Guid storeId = typeof(IPropertyStore).GUID;
            IPropertyStore store;
            Marshal.ThrowExceptionForHR(SHGetPropertyStoreForWindow(window, ref storeId, out store));
            try
            {
                string iconPath = Path.Combine(Path.GetDirectoryName(exePath), "Meeting Studio.ico");
                SetStringProperty(store, 2, "\"" + exePath + "\"");
                SetStringProperty(store, 3, (File.Exists(iconPath) ? iconPath : exePath) + ",0");
                SetStringProperty(store, 4, "Meeting Studio");
                SetStringProperty(store, 5, appId);
                Marshal.ThrowExceptionForHR(store.Commit());
            }
            finally { Marshal.FinalReleaseComObject(store); }
        }

        private static void SetStringProperty(IPropertyStore store, uint propertyId, string text)
        {
            PROPERTYKEY key = new PROPERTYKEY(new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), propertyId);
            PROPVARIANT value = PROPVARIANT.FromString(text);
            try { Marshal.ThrowExceptionForHR(store.SetValue(ref key, ref value)); }
            finally { PropVariantClear(ref value); }
        }

        internal static void ClearWindowIdentity(IntPtr window)
        {
            Guid storeId = typeof(IPropertyStore).GUID;
            IPropertyStore store;
            Marshal.ThrowExceptionForHR(SHGetPropertyStoreForWindow(window, ref storeId, out store));
            try
            {
                foreach (uint propertyId in new uint[] { 2, 3, 4, 5 })
                {
                    PROPERTYKEY key = new PROPERTYKEY(new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), propertyId);
                    PROPVARIANT empty = new PROPVARIANT(); // VT_EMPTY releases the window-store value.
                    Marshal.ThrowExceptionForHR(store.SetValue(ref key, ref empty));
                }
                Marshal.ThrowExceptionForHR(store.Commit());
            }
            finally { Marshal.FinalReleaseComObject(store); }
        }

        [DllImport("shell32.dll")]
        private static extern int SHGetPropertyStoreForWindow(IntPtr window, ref Guid interfaceId,
            [MarshalAs(UnmanagedType.Interface)] out IPropertyStore store);

        [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
        private static extern void SHChangeNotify(uint eventId, uint flags,
            [MarshalAs(UnmanagedType.LPWStr)] string item, IntPtr other);

        [DllImport("ole32.dll")]
        private static extern int PropVariantClear(ref PROPVARIANT value);

        [StructLayout(LayoutKind.Sequential)]
        private struct PROPERTYKEY
        {
            public Guid formatId;
            public uint propertyId;
            public PROPERTYKEY(Guid formatId, uint propertyId)
            {
                this.formatId = formatId;
                this.propertyId = propertyId;
            }
        }

        // The two pointer-sized fields preserve PROPVARIANT's native union size
        // on both x86 and x64. VT_LPWSTR uses the first pointer only.
        [StructLayout(LayoutKind.Sequential)]
        private struct PROPVARIANT
        {
            public ushort type;
            private ushort reserved1;
            private ushort reserved2;
            private ushort reserved3;
            public IntPtr pointer;
            private IntPtr unionPadding;

            public static PROPVARIANT FromString(string text)
            {
                PROPVARIANT value = new PROPVARIANT();
                value.type = 31; // VT_LPWSTR
                value.pointer = Marshal.StringToCoTaskMemUni(text);
                return value;
            }
        }

        [ComImport]
        [Guid("00021401-0000-0000-C000-000000000046")]
        [ClassInterface(ClassInterfaceType.None)]
        private class ShellLink { }

        [ComImport]
        [Guid("000214F9-0000-0000-C000-000000000046")]
        [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        private interface IShellLinkW
        {
            void GetPath([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder path,
                int maximumPath, IntPtr findData, uint flags);
            void GetIDList(out IntPtr itemIdList);
            void SetIDList(IntPtr itemIdList);
            void GetDescription([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder description, int maximum);
            void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string description);
            void GetWorkingDirectory([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder directory, int maximum);
            void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string directory);
            void GetArguments([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder arguments, int maximum);
            void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string arguments);
            void GetHotkey(out short hotkey);
            void SetHotkey(short hotkey);
            void GetShowCmd(out int command);
            void SetShowCmd(int command);
            void GetIconLocation([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder iconPath,
                int maximum, out int iconIndex);
            void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string iconPath, int iconIndex);
            void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string path, uint reserved);
            void Resolve(IntPtr window, uint flags);
            void SetPath([MarshalAs(UnmanagedType.LPWStr)] string path);
        }

        [ComImport]
        [Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")]
        [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        private interface IPropertyStore
        {
            [PreserveSig] int GetCount(out uint count);
            [PreserveSig] int GetAt(uint index, out PROPERTYKEY key);
            [PreserveSig] int GetValue(ref PROPERTYKEY key, out PROPVARIANT value);
            [PreserveSig] int SetValue(ref PROPERTYKEY key, ref PROPVARIANT value);
            [PreserveSig] int Commit();
        }
    }
}
