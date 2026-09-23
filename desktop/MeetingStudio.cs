using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Reflection;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

[assembly: AssemblyTitle("Meeting Studio")]
[assembly: AssemblyDescription("Local recordings, speaker transcripts, and meeting notes")]
[assembly: AssemblyProduct("Meeting Studio")]
[assembly: AssemblyVersion("1.1.0.0")]
[assembly: AssemblyFileVersion("1.1.0.0")]

namespace MeetingStudioDesktop
{
    internal static class Program
    {
        internal const string AppId = "MeetingStudio.Local.Desktop";
        internal static readonly string AppDirectory = AppDomain.CurrentDomain.BaseDirectory;
        internal const string AppUrl = "http://127.0.0.1:8766";
        internal static string SmokeOutput;
        [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
        private static extern int SetCurrentProcessExplicitAppUserModelID(string appId);

        [STAThread]
        private static int Main(string[] args)
        {
            if (args.Contains("--install-shortcuts"))
            {
                try { ShortcutInstaller.Install(Application.ExecutablePath, AppId); return 0; }
                catch (Exception ex) { MessageBox.Show(ex.Message, "Meeting Studio shortcuts"); return 1; }
            }
            if (args.Length == 2 && args[0] == "--smoke-test") SmokeOutput = Path.GetFullPath(args[1]);
            SetCurrentProcessExplicitAppUserModelID(AppId);
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            bool first;
            string instanceName = AppId + (SmokeOutput == null ? "" : ".Test");
            using (var singleton = new Mutex(true, @"Local\" + instanceName, out first))
            using (var activate = new EventWaitHandle(false, EventResetMode.AutoReset, @"Local\" + instanceName + ".Activate"))
            {
                if (!first) { activate.Set(); return 0; }
                using (var window = new StudioWindow())
                {
                    var registration = ThreadPool.RegisterWaitForSingleObject(activate, delegate {
                        try { if (!window.IsDisposed && !window.Disposing && window.IsHandleCreated) window.BeginInvoke((Action)window.BringBack); } catch (InvalidOperationException) { }
                    }, null, Timeout.Infinite, false);
                    Application.Run(window);
                    registration.Unregister(null);
                }
                singleton.ReleaseMutex();
            }
            return Environment.ExitCode;
        }
    }

    internal sealed class StudioWindow : Form
    {
        private readonly Label message;
        private readonly WebView2 browser;
        private readonly HttpClient http;
        private readonly CancellationTokenSource closing = new CancellationTokenSource();
        private bool smokeStarted;
        private TaskCompletionSource<string> smokeDownload;

        public StudioWindow()
        {
            Text = "Meeting Studio";
            string iconPath = Path.Combine(Program.AppDirectory, "Meeting Studio.ico");
            Icon = File.Exists(iconPath) ? new Icon(iconPath, 48, 48) : Icon.ExtractAssociatedIcon(Application.ExecutablePath);
            ShowIcon = true;
            Size = new Size(1320, 880);
            MinimumSize = new Size(900, 620);
            StartPosition = FormStartPosition.CenterScreen;
            WindowState = FormWindowState.Maximized;
            BackColor = Color.FromArgb(246, 245, 239);
            AutoScaleMode = AutoScaleMode.Dpi;
            message = new Label { Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleCenter,
                Font = new Font("Segoe UI", 13), ForeColor = Color.FromArgb(26, 73, 65),
                Text = "Opening your recording library..." };
            browser = new WebView2 { Dock = DockStyle.Fill, Visible = false,
                DefaultBackgroundColor = BackColor };
            Controls.Add(browser);
            Controls.Add(message);
            http = new HttpClient(new HttpClientHandler { UseProxy = false }) { Timeout = TimeSpan.FromSeconds(8) };
            if (Program.SmokeOutput != null)
            {
                WindowState = FormWindowState.Normal;
                Size = new Size(Math.Min(Screen.PrimaryScreen.WorkingArea.Width - 80, 2400), Math.Min(Screen.PrimaryScreen.WorkingArea.Height - 80, 1600));
                ShowInTaskbar = false;
                StartPosition = FormStartPosition.Manual;
                Location = new Point(-18000, -18000);
            }
            Shown += async delegate { await OpenStudio(); };
            FormClosed += delegate { closing.Cancel(); browser.Dispose(); http.Dispose(); };
        }

        internal void BringBack()
        {
            if (WindowState == FormWindowState.Minimized) WindowState = FormWindowState.Normal;
            Show();
            Activate();
        }

        protected override void OnHandleCreated(EventArgs e)
        {
            base.OnHandleCreated(e);
            // Give Windows both the window identity and a stable taskbar icon.
            // This also supplies the correct icon when pinned directly from a window.
            try { ShortcutInstaller.SetWindowIdentity(Handle, Application.ExecutablePath, Program.AppId); }
            catch (COMException ex) { Trace.WriteLine("Taskbar identity could not be set: " + ex.Message); }
        }

        protected override void DestroyHandle()
        {
            if (IsHandleCreated)
            {
                try { ShortcutInstaller.ClearWindowIdentity(Handle); }
                catch (COMException ex) { Trace.WriteLine("Taskbar identity cleanup failed: " + ex.Message); }
            }
            base.DestroyHandle();
        }

        private async Task<bool> BackendReady()
        {
            HttpResponseMessage response;
            try { response = await http.GetAsync(Program.AppUrl + "/api/status", closing.Token); }
            catch (HttpRequestException) { return false; }
            catch (TaskCanceledException) { if (closing.IsCancellationRequested) throw; return false; }
            using (response)
            {
                var body = await response.Content.ReadAsStringAsync();
                try
                {
                    var status = new JavaScriptSerializer().Deserialize<System.Collections.Generic.Dictionary<string, object>>(body);
                    if (response.IsSuccessStatusCode && status.ContainsKey("app") && (string)status["app"] == "Meeting Studio") return true;
                }
                catch (Exception) { }
                throw new InvalidOperationException("Another program is using Meeting Studio's local address (port 8766). Close that program and reopen Meeting Studio.");
            }
        }

        private static bool PortInUse()
        {
            using (var client = new TcpClient())
            {
                try { client.Connect(IPAddress.Loopback, 8766); return true; }
                catch (SocketException) { return false; }
            }
        }

        private static Process StartBackend()
        {
            string python = Path.Combine(Program.AppDirectory, @".venv\Scripts\python.exe");
            string configPath = Path.Combine(Program.AppDirectory, "runtime.json");
            if (File.Exists(configPath))
            {
                var config = new JavaScriptSerializer().Deserialize<System.Collections.Generic.Dictionary<string, object>>(File.ReadAllText(configPath));
                object configured;
                if (config.TryGetValue("python", out configured) && File.Exists(Convert.ToString(configured))) python = Convert.ToString(configured);
            }
            if (!File.Exists(python)) throw new FileNotFoundException("Run Install.cmd in the Meeting Studio folder once to prepare this computer.");
            string pythonWindowless = Path.Combine(Path.GetDirectoryName(python), "pythonw.exe");
            if (File.Exists(pythonWindowless)) python = pythonWindowless;
            Directory.CreateDirectory(Path.Combine(Program.AppDirectory, "data"));
            // No redirected pipes: the backend owns its logs and survives closing this window.
            var start = new ProcessStartInfo(python, "\"" + Path.Combine(Program.AppDirectory, @"desktop\server_runner.py") + "\"") {
                WorkingDirectory = Program.AppDirectory, UseShellExecute = false, CreateNoWindow = true,
                WindowStyle = ProcessWindowStyle.Hidden };
            var process = Process.Start(start);
            File.WriteAllText(Path.Combine(Program.AppDirectory, @"data\server.pid"), process.Id.ToString());
            return process;
        }

        private async Task OpenStudio()
        {
            try
            {
                // Check WebView2 before starting work in the background.
                CoreWebView2Environment.GetAvailableBrowserVersionString();
                if (!await BackendReady())
                {
                    Process started = null;
                    if (!PortInUse()) started = StartBackend();
                    try
                    {
                        var wait = Stopwatch.StartNew();
                        while (!await BackendReady())
                        {
                            if (started != null && started.HasExited)
                                throw new InvalidOperationException("The local app could not start. See data\\server-errors.log in the Meeting Studio folder.");
                            if (wait.Elapsed.TotalSeconds > 60)
                                throw new TimeoutException("The local app is taking too long to respond. Try reopening Meeting Studio. Details are in data\\server-errors.log.");
                            await Task.Delay(700, closing.Token);
                        }
                    }
                    finally { if (started != null) started.Dispose(); }
                }
                string profile = Path.Combine(Program.AppDirectory, "data", Program.SmokeOutput == null ? "desktop-profile" : "desktop-test-profile");
                var environment = await CoreWebView2Environment.CreateAsync(null, profile);
                await browser.EnsureCoreWebView2Async(environment);
                var core = browser.CoreWebView2;
                core.Settings.AreDevToolsEnabled = false;
                core.Settings.IsStatusBarEnabled = false;
                core.Settings.IsPasswordAutosaveEnabled = false;
                core.Settings.IsGeneralAutofillEnabled = false;
                core.Settings.AreHostObjectsAllowed = false;
                core.Settings.IsWebMessageEnabled = false;
                core.NavigationStarting += delegate(object sender, CoreWebView2NavigationStartingEventArgs e) {
                    if (!IsAppAddress(e.Uri)) e.Cancel = true;
                };
                core.FrameNavigationStarting += delegate(object sender, CoreWebView2NavigationStartingEventArgs e) { if (!IsAppAddress(e.Uri)) e.Cancel = true; };
                core.NewWindowRequested += delegate(object sender, CoreWebView2NewWindowRequestedEventArgs e) {
                    e.Handled = true;
                    if (IsAppAddress(e.Uri)) core.Navigate(e.Uri);
                };
                core.PermissionRequested += delegate(object sender, CoreWebView2PermissionRequestedEventArgs e) {
                    e.State = CoreWebView2PermissionState.Deny;
                };
                core.DownloadStarting += DownloadStarting;
                core.ProcessFailed += delegate(object sender, CoreWebView2ProcessFailedEventArgs e) {
                    message.Text = "The app window stopped responding. Close and reopen Meeting Studio. Your saved recordings are still on this computer.";
                    message.Visible = true; message.BringToFront();
                };
                core.NavigationCompleted += async delegate(object sender, CoreWebView2NavigationCompletedEventArgs e) {
                    if (!e.IsSuccess)
                    {
                        // Export navigations may report ConnectionAborted when handed to DownloadStarting.
                        if (e.WebErrorStatus == CoreWebView2WebErrorStatus.ConnectionAborted) return;
                        Fail(new InvalidOperationException("The recording library could not load: " + e.WebErrorStatus));
                        return;
                    }
                    message.Visible = false;
                    browser.Visible = true;
                    browser.BringToFront();
                    if (Program.SmokeOutput != null && !smokeStarted)
                    {
                        smokeStarted = true;
                        await RunSmokeTest();
                    }
                };
                core.Navigate(Program.AppUrl);
            }
            catch (OperationCanceledException) { }
            catch (WebView2RuntimeNotFoundException) {
                Fail(new InvalidOperationException("Microsoft Edge WebView2 Runtime is needed. Install it from Microsoft's WebView2 download page, then reopen Meeting Studio. Start in browser.ps1 is also available in the app folder."));
            }
            catch (Exception ex) { Fail(ex); }
        }

        private static bool IsAppAddress(string address)
        {
            Uri uri;
            return Uri.TryCreate(address, UriKind.Absolute, out uri) && uri.Scheme == "http" &&
                uri.Host == "127.0.0.1" && uri.Port == 8766 && String.IsNullOrEmpty(uri.UserInfo);
        }

        private void DownloadStarting(object sender, CoreWebView2DownloadStartingEventArgs e)
        {
            e.Handled = true;
            if (!IsAppAddress(e.DownloadOperation.Uri)) { e.Cancel = true; return; }
            if (Program.SmokeOutput != null)
            {
                e.ResultFilePath = Path.Combine(Path.GetDirectoryName(Program.SmokeOutput), "desktop-export-test.docx");
                var operation = e.DownloadOperation;
                operation.StateChanged += delegate {
                    if (smokeDownload == null) return;
                    if (operation.State == CoreWebView2DownloadState.Completed) smokeDownload.TrySetResult(e.ResultFilePath);
                    else if (operation.State == CoreWebView2DownloadState.Interrupted) smokeDownload.TrySetException(new IOException("Export download interrupted: " + operation.InterruptReason));
                };
                return;
            }
            var deferral = e.GetDeferral();
            try { BeginInvoke((Action)delegate {
            try
            {
                using (var dialog = new SaveFileDialog { Title = "Save meeting document", FileName = Path.GetFileName(e.ResultFilePath),
                    InitialDirectory = Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments),
                    Filter = "Meeting documents|*.docx;*.md;*.json|All files|*.*", RestoreDirectory = true, OverwritePrompt = true })
                {
                    if (dialog.ShowDialog(this) == DialogResult.OK) e.ResultFilePath = dialog.FileName;
                    else e.Cancel = true;
                }
            }
            finally { deferral.Complete(); }
            }); } catch (InvalidOperationException) { e.Cancel = true; deferral.Complete(); }
        }

        private async Task RunSmokeTest()
        {
            try
            {
                var core = browser.CoreWebView2;
                string ready = "false";
                for (int i = 0; i < 60 && ready != "true"; i++)
                {
                    await Task.Delay(500);
                    ready = await core.ExecuteScriptAsync("document.title === 'Meeting Studio' && !!document.querySelector('#new-recording') && !document.querySelector('#connection-text').textContent.includes('Connecting')");
                }
                if (ready != "true") throw new Exception("App did not finish loading.");
                string status = await core.ExecuteScriptAsync("JSON.stringify({title: document.title, status: document.querySelector('#connection-text').textContent, library: document.querySelector('#library-count').textContent, width: innerWidth})");
                // Exercise a real browser download through the embedded window when a demo exists.
                string exportUrl = await core.ExecuteScriptAsync("document.querySelector('#export-docx')?.getAttribute('href') || ''");
                var serializer = new JavaScriptSerializer();
                string href = serializer.Deserialize<string>(exportUrl);
                string downloaded = "No completed recording selected";
                if (!String.IsNullOrEmpty(href) && href.StartsWith("/api/jobs/"))
                {
                    smokeDownload = new TaskCompletionSource<string>();
                    await core.ExecuteScriptAsync("document.querySelector('#export-docx').click()");
                    if (await Task.WhenAny(smokeDownload.Task, Task.Delay(30000)) != smokeDownload.Task) throw new Exception("Export download timed out.");
                    downloaded = await smokeDownload.Task;
                    if (new FileInfo(downloaded).Length < 100) throw new Exception("Export file was empty.");
                }
                using (var screenshot = File.Create(Path.ChangeExtension(Program.SmokeOutput, ".png")))
                    await core.CapturePreviewAsync(CoreWebView2CapturePreviewImageFormat.Png, screenshot);
                File.WriteAllText(Program.SmokeOutput, serializer.Serialize(new { success = true, window = serializer.Deserialize<string>(status), download = downloaded,
                    appId = Program.AppId, runtime = core.Environment.BrowserVersionString }));
            }
            catch (Exception ex) { WriteSmokeFailure(ex); }
            finally { Close(); }
        }

        private void WriteSmokeFailure(Exception ex)
        {
            Environment.ExitCode = 1;
            File.WriteAllText(Program.SmokeOutput, new JavaScriptSerializer().Serialize(new { success = false, error = ex.ToString() }));
        }

        private void Fail(Exception ex)
        {
            if (IsDisposed) return;
            if (Program.SmokeOutput != null) { WriteSmokeFailure(ex); Close(); return; }
            message.Text = "Meeting Studio could not open\n\n" + ex.Message;
            message.Padding = new Padding(65);
            message.Visible = true;
            message.BringToFront();
        }
    }
}
