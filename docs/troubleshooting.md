# Troubleshooting

Common issues and fixes.

## Ctrl+C doesn't stop the orchestrator

Fixed in Jan 2026. The orchestrator now uses:
- Async subprocess calls (don't block event loop)
- Proper process termination on timeout
- 5-second shutdown timeout with force-exit fallback
- Second Ctrl+C forces immediate exit

If still having issues, check if a child process (signal-cli, claude) is stuck.

## Orchestrator won't start

1. Check Python: `python --version`
2. Check dependencies: `pip install -r requirements.txt`
3. Check config: Does `config/settings.yaml` exist?
4. Check signal-cli: `signal-cli --version`

## Not receiving messages

1. Is signal-cli linked? `signal-cli -u +PHONE receive`
2. Phone number correct in settings?
3. Group ID correct? `signal-cli -u +PHONE listGroups`

## Claude not responding

1. Check trigger word in settings
2. Claude Code installed? `claude --version`
3. Check orchestrator logs for errors

## OBS monitor failing

1. Is OBS running?
2. WebSocket enabled? (Tools → WebSocket Server Settings)
3. Password correct in settings?

## signal-cli issues

See `docs/signal-cli.md` for detailed patterns and gotchas.

Key points:
- `--output json` goes BEFORE subcommand
- Mentions use U+FFFC placeholder, check `mentions` array
- Windows may need `--message-from-stdin` for newlines

## Disk fills up from libsignal temp folders (Windows)

**Symptom:** Disk at 0% free, thousands of `libsignalXXXXXXXX` folders in `%TEMP%\2\`.

**Cause:** libsignal-client extracts its native DLL to a randomly-named temp folder on every invocation. It tries `deleteOnExit()` but Windows can't delete loaded DLLs. Running 24/7 = thousands of 20MB folders.

**Fix applied (Jan 2026):** Pre-extracted the DLL so libsignal finds it without extracting.

Location: `C:\signal-cli\native-lib\signal_jni.dll`

Modified: `C:\signal-cli\signal-cli-0.13.22\bin\signal-cli.bat` - added `-Djava.library.path=C:\signal-cli\native-lib` to DEFAULT_JVM_OPTS.

**If updating signal-cli:**
1. Extract new DLL: `Expand-Archive lib\libsignal-client-X.X.X.jar -DestinationPath temp`
2. Copy: `Copy-Item temp\signal_jni_amd64.dll C:\signal-cli\native-lib\signal_jni.dll`
3. Check batch file still has the `-Djava.library.path` flag

**Backup cleanup:** The orchestrator runs hourly cleanup of old libsignal folders as a safety net. If folders are found, it logs a warning (early detection that the fix isn't working). Configure via `temp_cleanup_interval` in settings.yaml (set to 0 to disable).

**References:**
- https://github.com/AsamK/signal-cli/wiki/Provide-native-lib-for-libsignal
- https://github.com/tensorflow/tensorflow/issues/18397 (same root cause)
