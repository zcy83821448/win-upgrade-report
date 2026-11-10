using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Pipes;
using System.Threading;
using System.Threading.Tasks;

namespace WinUpd
{
    /// <summary>和 Python 后台服务（命名管道）通信，并在需要时自动拉起服务进程。</summary>
    public sealed class UiClient : IDisposable
    {
        public event Action<bool, string> ConnectionChanged;

        private readonly object _sync = new object();
        private readonly object _writeLock = new object();
        private readonly Dictionary<long, TaskCompletionSource<Dictionary<string, object>>> _pending
            = new Dictionary<long, TaskCompletionSource<Dictionary<string, object>>>();
        private readonly TaskCompletionSource<bool> _everReady
            = new TaskCompletionSource<bool>();

        private Process _proc;
        private NamedPipeClientStream _inPipe;
        private NamedPipeClientStream _outPipe;
        private StreamReader _reader;
        private StreamWriter _writer;
        private Thread _readThread;
        private Thread _connectThread;
        private long _nextId;
        private volatile bool _connected;
        private volatile bool _disposed;
        private int _reportedFailure;

        public bool Connected { get { return _connected; } }
        public bool EverReady { get { return _everReady.Task.IsCompleted; } }

        // ---------------------------------------------------------------- 启动
        public void Start()
        {
            _connectThread = new Thread(ConnectLoop);
            _connectThread.IsBackground = true;
            _connectThread.Name = "ui-connect";
            _connectThread.Start();
        }

        private void ConnectLoop()
        {
            bool firstRound = true;
            while (!_disposed)
            {
                try
                {
                    if (_proc == null || HasExitedSafe(_proc))
                        StartProcess();
                    ConnectPipe();
                    OnConnected();
                    return;
                }
                catch (Exception e)
                {
                    if (firstRound)
                    {
                        Interlocked.Exchange(ref _reportedFailure, 1);
                        AppEnv.Log("连接后台服务失败：" + e.Message);
                        firstRound = false;
                    }
                    Thread.Sleep(150);
                }
            }
        }

        private void StartProcess()
        {
            ProcessStartInfo psi = AppEnv.BuildServiceStartInfo();
            var proc = new Process { StartInfo = psi, EnableRaisingEvents = true };
            proc.Start();
            _proc = proc;
        }

        private static bool HasExitedSafe(Process p)
        {
            try { return p.HasExited; }
            catch { return true; }
        }

        private void ConnectPipe()
        {
            // 收发走两条单向管道：同步句柄上同时 ReadFile/WriteFile 会互相卡住。
            var inPipe = new NamedPipeClientStream(".", AppEnv.PipeName,
                PipeDirection.Out);
            try
            {
                inPipe.Connect(700);
            }
            catch
            {
                inPipe.Dispose();
                throw;
            }
            var outPipe = new NamedPipeClientStream(".", AppEnv.PipeName + "-out",
                PipeDirection.In);
            try
            {
                outPipe.Connect(1500);
            }
            catch
            {
                try { inPipe.Dispose(); } catch { }
                try { outPipe.Dispose(); } catch { }
                throw;
            }
            var reader = new StreamReader(outPipe, new System.Text.UTF8Encoding(false),
                false, 65536, true);
            var writer = new StreamWriter(inPipe, new System.Text.UTF8Encoding(false),
                65536, true);
            writer.AutoFlush = true;
            lock (_writeLock)
            {
                _inPipe = inPipe;
                _outPipe = outPipe;
                _reader = reader;
                _writer = writer;
            }
            _readThread = new Thread(ReadLoop);
            _readThread.IsBackground = true;
            _readThread.Name = "ui-read";
            _readThread.Start();
        }

        private void ReadLoop()
        {
            try
            {
                while (!_disposed)
                {
                    string line = _reader.ReadLine();
                    if (line == null) break;
                    if (line.Length == 0) continue;
                    Dictionary<string, object> msg;
                    try { msg = Json.Deserialize(line); }
                    catch { continue; }
                    long id = Json.Long(msg, "id", 0);
                    if (id <= 0) continue;
                    TaskCompletionSource<Dictionary<string, object>> tcs = null;
                    lock (_sync)
                    {
                        if (_pending.TryGetValue(id, out tcs)) _pending.Remove(id);
                    }
                    if (tcs != null) tcs.TrySetResult(msg);
                }
            }
            catch (Exception e)
            {
                if (!_disposed) AppEnv.Log("读取后台响应失败：" + e.Message);
            }
            finally
            {
                OnDisconnected();
            }
        }

        private void OnConnected()
        {
            _connected = true;
            _everReady.TrySetResult(true);
            var h = ConnectionChanged;
            if (h != null) h(true, "");
        }

        private void OnDisconnected()
        {
            if (!_connected) return;
            _connected = false;
            lock (_sync)
            {
                foreach (var kv in _pending)
                    kv.Value.TrySetException(new IOException("后台服务已断开"));
                _pending.Clear();
            }
            var h = ConnectionChanged;
            if (h != null) h(false, "后台连接中断，正在自动重连…");
            if (_disposed) return;
            var t = new Thread(ReconnectLoop);
            t.IsBackground = true;
            t.Name = "ui-reconnect";
            t.Start();
        }

        private void ReconnectLoop()
        {
            int failures = 0;
            while (!_disposed && !_connected)
            {
                try
                {
                    if (_proc == null || HasExitedSafe(_proc))
                        StartProcess();
                    ConnectPipe();
                    OnConnected();
                    return;
                }
                catch
                {
                    failures++;
                    if (failures == 10)
                        AppEnv.Log("后台服务重连多次失败：" + AppEnv.ServiceDescription());
                    Thread.Sleep(400);
                }
            }
        }

        // ---------------------------------------------------------------- 请求
        public async Task<Dictionary<string, object>> RequestAsync(
            string cmd, Dictionary<string, object> args = null, int timeoutMs = 20000)
        {
            if (_disposed) return Error("程序正在退出");
            if (!_connected)
            {
                Task ready = _everReady.Task;
                Task readyDone = await Task.WhenAny(ready, Task.Delay(
                    Math.Min(timeoutMs, 15000))).ConfigureAwait(false);
                if (!_connected) return Error("后台服务还没连上，请稍等一秒再试");
            }

            long id = Interlocked.Increment(ref _nextId);
            App.Boot("Req " + cmd + ": id=" + id);
            var tcs = new TaskCompletionSource<Dictionary<string, object>>();
            lock (_sync) _pending[id] = tcs;
            App.Boot("Req " + cmd + ": pending added");
            var payload = new Dictionary<string, object>
            {
                { "id", id },
                { "cmd", cmd },
                { "args", args ?? new Dictionary<string, object>() }
            };
            try
            {
                App.Boot("Req " + cmd + ": before serialize");
                string line = Json.Serialize(payload);
                App.Boot("Req " + cmd + ": before write lock");
                lock (_writeLock)
                {
                    if (_writer == null) throw new IOException("管道未连接");
                    _writer.WriteLine(line);
                    _writer.Flush();
                }
                App.Boot("Req " + cmd + ": written");
            }
            catch (Exception e)
            {
                lock (_sync) _pending.Remove(id);
                return Error("后台服务连接出错：" + e.Message);
            }

            Task done = await Task.WhenAny(tcs.Task, Task.Delay(timeoutMs))
                .ConfigureAwait(false);
            if (done != tcs.Task)
            {
                lock (_sync) _pending.Remove(id);
                return Error("操作超时（后台还在处理？）");
            }
            try { return await tcs.Task.ConfigureAwait(false); }
            catch (Exception e) { return Error("后台服务连接出错：" + e.Message); }
        }

        // ---------------------------------------------------------------- 便捷
        public static bool IsOk(IDictionary<string, object> resp)
        {
            return resp != null && Json.Bool(resp, "ok", false);
        }

        public static Dictionary<string, object> Result(IDictionary<string, object> resp)
        {
            return Json.Dict(resp, "result");
        }

        public static string ErrorOf(IDictionary<string, object> resp)
        {
            if (resp == null) return "没有响应";
            string err = Json.Str(resp, "error");
            if (!string.IsNullOrEmpty(err)) return err;
            var result = Json.Dict(resp, "result");
            if (result != null)
            {
                string inner = Json.Str(result, "error");
                if (!string.IsNullOrEmpty(inner)) return inner;
                string message = Json.Str(result, "message");
                if (!string.IsNullOrEmpty(message)) return message;
            }
            return "操作失败";
        }

        public static Dictionary<string, object> Error(string text)
        {
            return new Dictionary<string, object>
            {
                { "ok", false },
                { "error", text },
                { "result", new Dictionary<string, object>() }
            };
        }

        // ---------------------------------------------------------------- 收尾
        public void Dispose()
        {
            if (_disposed) return;
            _disposed = true;
            _connected = false;
            try
            {
                if (_connected || _writer != null)
                {
                    lock (_writeLock)
                    {
                        if (_writer != null)
                        {
                            _writer.WriteLine(Json.Serialize(new Dictionary<string, object>
                            {
                                { "id", -1 }, { "cmd", "shutdown" },
                                { "args", new Dictionary<string, object>() }
                            }));
                            _writer.Flush();
                        }
                    }
                }
            }
            catch { }
            try { if (_inPipe != null) _inPipe.Dispose(); } catch { }
            try { if (_outPipe != null) _outPipe.Dispose(); } catch { }
            try
            {
                if (_proc != null && !HasExitedSafe(_proc))
                {
                    if (!_proc.WaitForExit(1200)) _proc.Kill();
                }
            }
            catch { }
        }
    }
}



