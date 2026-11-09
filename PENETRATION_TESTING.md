# Argon MCP Harness — Penetration, Stress & Edge-Case Test Documentation (`PENETRATION_TESTING.md`)

> **Date:** 2026-11-09  
> **Project Root:** `C:\Workspace\Projects\argon-mcp-harness`  
> **Primary Focus:** Python Execution, Compaction, Workspace Isolation, Prefix-Cache Scrubbing & Process Tree Resilience

---

## 1. Executive Summary

Bu doküman, `argon-mcp-harness` MCP sunucusunun hem ilk mimari geçiş sürecinde (`tests/test_harness_e2e.py`) hem de Python ağırlıklı penetrasyon ve stres testlerinde (`tests/test_python_penetration.py`) gerçekleştirilen tüm test senaryolarını, tespit edilen zafiyetleri/hataları, uygulanan düzeltmeleri ve gelecek fazlar için planlanan testleri kayıt altına alır.

---

## 2. Tamamlanan Temel Regresyon ve E2E Testleri (`tests/test_harness_e2e.py`)

İlk aşamada tespit edilen 6 temel mimari hatanın doğrulama testleri:

| Test Kodu | Test Adı (`TestArgonHarness`) | Hedeflenen Hata / Senaryo | Durum |
| :--- | :--- | :--- | :---: |
| **E2E-01** | `test_bug1_exit_zero_preserves_stdout_and_unittest_summary` | `EXIT: 0` durumunda normal Python betik çıktılarının (`stdout`) ve `unittest` özetlerinin (`stderr`) yutulmaması, son 20 satır / 1000 karakter olarak normalize edilip korunması. | ✅ PASS |
| **E2E-02** | `test_bug2_cpp_adapter_flag_injection_and_text_diagnostics` | `clang`/`clang++` komutlarına `-fdiagnostics-format=json` enjekte edilmemesi; `g++` kelime sınırı (`(?=\s\|$)`), `--version`/`-E` koruması ve CMake/Ninja altındaki düz metin C/C++ hatalarının kaynak kodu penceresiyle (`fetch_source_window`) sıkıştırılması. | ✅ PASS |
| **E2E-03** | `test_bug3_duration_pid_scrubbing_and_loop_detection` | Çalışma süreleri (`0.001s` vs `0.049s`) ve süreç kimliklerinin (`pid=1234`) `[DURATION]` ve `PID=[PID]` olarak maskelenmesi; ardışık iki aynı hatada deterministik SHA-256 ile `[CRITICAL LOOP DETECTED]` üretilmesi. | ✅ PASS |
| **E2E-04** | `test_bug4_dynamic_log_file_and_inspect_raw_log` | `.antigravity/logs/last_run.log` dosyasının import anında değil, aktif `workdir` altında dinamik oluşturulması ve `inspect_raw_log` ile regex/tail sorgulanması. | ✅ PASS |
| **E2E-05** | `test_bug5_multiline_command_execution` | Windows `cmd.exe /c` altındaki çok satırlı (`\n`) komutların ilk satırda kesilmesinin önlenmesi; PowerShell adaptörü ile hem çok satırlı kabuk komutlarının hem de `python -c "x = 40\n..."` çağrılarının çıkış kodu korunarak yürütülmesi. | ✅ PASS |
| **E2E-06** | `test_bug6_python_unittest_compaction_and_source_window` | Python `unittest` hata bloklarının `max_errors` sınırına göre budanması, en içteki proje çerçevesinin (`cwd` altı) bulunması ve `+/-2` satır kaynak kodu penceresi eklenmesi. | ✅ PASS |
| **E2E-07** | `test_rust_adapter_json_and_source_window` | `RustAdapter` ile `cargo check` JSON çıktılarının (`E0308`) ve kaynak kodu penceresinin doğrulanması. | ✅ PASS |
| **E2E-08** | `test_jsonrpc_stdio_e2e` | `argon_harness_mcp.py` alt sürecinin gerçek `stdin`/`stdout` üzerinden `initialize`, `tools/list` ve `tools/call` JSON-RPC 2.0 mesajlarıyla uçtan uca doğrulanması. | ✅ PASS |

---

## 3. Tamamlanan Python Ağırlıklı Penetrasyon & Stres Testleri (`tests/test_python_penetration.py`)

Python çalışma zamanı, `PythonAdapter`, `normalizer`, `source_window` ve `ExecutionEngine` bileşenlerine yönelik gerçekleştirilen 10 ileri seviye penetrasyon ve sınır testi:

| Test Kodu | Test Adı (`TestPythonPenetration`) | Saldırı Vektörü / Stres Senaryosu | Tespit Edilen Zafiyet & Uygulanan Çözüm | Durum |
| :--- | :--- | :--- | :--- | :---: |
| **PT-01** | `test_pt01_chained_exceptions_grouped_as_single_root_error` | **Zincirleme İstisnalar (`raise ... from ...` ve örtük zincirleme)**: 3 katmanlı (`ZeroDivisionError` -> `KeyError` -> `RuntimeError`) bir Python hatası. | **Bulgular:** Eski regex her `Traceback` başlığını ayrı bir kök hata sanıp `max_errors` kotasını tüketiyordu.<br>**Çözüm:** `_extract_traceback_chains` ile `direct cause` ve `another exception occurred` bağlaçları doğrusal zamanda ($O(N)$) birleştirilerek tek kök hata (`Chained Traceback #1`) olarak gruplandı. | ✅ PASS |
| **PT-02** | `test_pt02_exception_group_compaction` | **Python 3.11+ `ExceptionGroup` / `BaseExceptionGroup`**: Eşzamanlı görev hatalarında üretilen `+ Exception Group Traceback` çıktısı. | **Bulgular:** `+ Exception Group Traceback` başlığı standart regex tarafından tanınmıyordu.<br>**Çözüm:** `TRACEBACK_HEADER_REGEX` ve `_extract_exception_line` ağaç öneklerini (`\|+ `) destekleyecek şekilde genişletildi. | ✅ PASS |
| **PT-03** | `test_pt03_syntax_and_indentation_errors` | **`Traceback` Başlığı Olmayan Derleme/Sözdizimi Hataları**: `SyntaxError`, `IndentationError`, `TabError`. | **Bulgular:** İç içe `.*?` içeren eski regex büyük çıktılarda catastrophic backtracking (ReDoS) riski taşıyordu.<br>**Çözüm:** `_extract_syntax_errors` satır tabanlı doğrusal tarama ($O(N)$) ile yeniden yazıldı. | ✅ PASS |
| **PT-04** | `test_pt04_workspace_boundary_and_stdlib_frame_isolation` | **Path Traversal (`../`) & Stdlib Çerçeve Sızıntısı**: Traceback içinde `cwd` dışındaki bir dosyaya (`../secret.py`) veya Python stdlib (`Lib/unittest/case.py`) dosyasına referans verilmesi. | **Bulgular:** `fetch_source_window` çalışma dizini dışındaki dosyaları okuyabiliyordu ve `python -c` komutlarında `unittest/case.py` kaynak kodu sızıyordu.<br>**Çözüm:** `fetch_source_window` içine `target.is_relative_to(cwd_resolved)` sınır kontrolü eklendi; `_select_best_frame` içinden stdlib/framework (`unittest`, `_pytest`, `site-packages`, `importlib`) çerçeveleri dışlandı. | ✅ PASS |
| **PT-05** | `test_pt05_temp_path_and_microsecond_volatility_loop_detection` | **Geçici Dizin (`tempfile.mkdtemp`), Bellek Adresi (`<Obj at 0x...>`) ve Mikrosaniye (`µs`/`ns`) ile Loop Detection Atlatma**: Her çalışmada rastgele temp klasörü ve süre üreten hata. | **Bulgular:** `Temp\tmpXXXXXXXX` ve `pytest-NNN` yolları ile `us`/`µs`/`ns` birimleri temizlenmediği için SHA-256 özeti her seferinde değişiyordu.<br>**Çözüm:** `normalizer.py` içine `TEMP_PATH_REGEX` (`[TMPDIR]`), genişletilmiş `HEX_ADDR_REGEX` ve `ns\|us\|µs` birimleri eklendi. | ✅ PASS |
| **PT-06** | `test_pt06_pytest_flag_injection_position` | **Kabuk Operatörleriyle (`&&`, `\|`) Zincirlenmiş `pytest` Komutları**: `pytest tests/unit && echo DONE`. | **Bulgular:** Bayrakların komutun en sonuna eklenmesi `echo DONE --tb=short ...` şeklinde komutu bozuyordu.<br>**Çözüm:** `PYTEST_CMD_REGEX.sub` ile bayraklar doğrudan `pytest` token'ının hemen arkasına enjekte edildi. | ✅ PASS |
| **PT-07** | `test_pt07_massive_output_flood_resilience` | **5 MB Çıktı Tufanı (Output Bomb / Memory & ReDoS)**: Çökmeden önce 40.000 satır (~4 MB) gürültü basan Python betiği. | **Bulgular:** Devasa metinler üzerinde tam regex taraması gecikmeye yol açabiliyordu.<br>**Çözüm:** `PythonAdapter._cap_text` ile ayrıştırma penceresi 256 KB (ilk 128 KB + son 128 KB) ile sınırlandırıldı; 4 MB'lık çıktı <2 saniyede sıkıştırıldı. | ✅ PASS |
| **PT-08** | `test_pt08_timeout_kills_child_tree_and_saves_partial_log` | **Asılı Kalan Alt Süreç Ağacı (Orphan Child Process) & Kısmi Log Kaybı**: Alt süreç (`subprocess.Popen`) başlatıp 60sn uyuyan betik (`timeout=2s`). | **Bulgular:** 1) Windows sandbox altında `taskkill /F /T` yetki engeline takıldığında torun süreçler (`child`) pipe'ı açık tutarak `communicate()` çağrısını 60sn blokluyordu.<br>2) CPython `subprocess` üzerinde `_readerthread` yalnızca EOF anında `_stdout_buff` listesine yazıyordu.<br>**Çözüm:** `ctypes.windll.kernel32` üzerinden Windows Job Object (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE \| JOB_OBJECT_LIMIT_BREAKAWAY_OK`) bağlanarak tüm alt süreç ağacının çekirdek seviyesinde (`TerminateJobObject`) atomik olarak sonlandırılması sağlandı; ardından `_stdout_buff`/`_stderr_buff` hasat edilerek kısmi çıktı hem `last_run.log` dosyasına hem de `[Partial output before timeout]` özetine eklendi. | ✅ PASS |
| **PT-09** | `test_pt09_binary_bytes_and_unicode_resilience` | **Geçersiz UTF-8 Bayt Enjeksiyonu & ANSI/Unicode Karışımı**: `sys.stderr.buffer.write(b"\xff\xfe\xfd")` + Türkçe karakterler + ANSI renk kodları. | **Bulgular:** Bozuk bayt dizilerinin JSON-RPC serileştirmesini veya log yazımını kırma riski.<br>**Çözüm:** `errors="replace"` ve `PYTHONIOENCODING="utf-8"` ile sıfır çökme doğrulandı. | ✅ PASS |
| **PT-10** | `test_pt10_malformed_parameters_and_bad_regex_fuzzing` | **Bozuk Parametre & Geçersiz Regex Fuzzing**: Boş komut (`"   "`), `inspect_raw_log(grep_pattern="[unclosed_group")`, negatif `max_errors` ve `timeout`. | **Bulgular:** Geçersiz regex `re.error` fırlatarak aracı hata durumuna düşürüyordu.<br>**Çözüm:** `re.error` yakalanarak `[HARNESS ERROR] Invalid regex pattern` mesajına dönüştürüldü; `max_errors` ve `timeout` güvenli aralıklara (`clamp`) sınırlandı. | ✅ PASS |

---

## 4. Gelecek Fazlar İçin Planlanan Penetrasyon ve Stres Testleri (Roadmap)

Aşağıdaki test senaryoları bir sonraki iterasyonlarda test paketine (`tests/`) eklenecektir:

### Faz 2 — İleri Seviye Python & Çoklu Süreç (Multiprocessing / Asyncio) Testleri
- [ ] **PT-11 (`multiprocessing.Pool` & `ProcessPoolExecutor` Deadlock / Crash)**: Çöken worker süreçlerinin (`BrokenProcessPool`) ürettiği iç içe `RemoteTraceback` çıktılarının tek kök hata olarak ayrıştırılması.
- [ ] **PT-12 (`asyncio.TaskGroup` & Unawaited Coroutine Warnings)**: `asyncio` görev gruplarında oluşan çoklu `ExceptionGroup` ve `RuntimeWarning` çıktılarının gürültüden arındırılması.
- [ ] **PT-13 (Derin Özyineleme — `RecursionError`)**: 1000 çerçeveli `RecursionError: maximum recursion depth exceeded` çıktısında tekrarlayan çerçevelerin (`[Previous line repeated 996 more times]`) kaynak kodu penceresini bozmadan sıkıştırılması.
- [ ] **PT-14 (`pytest` Parametrize & Doctest Çıktıları)**: `@pytest.mark.parametrize` ile aynı testin 20 farklı parametreyle patlaması durumunda `max_errors` budamasının ve parametre özetinin doğrulanması.
- [ ] **PT-15 (C-Extension / NumPy / OpenCV Segfault & Native Crash)**: Python içinden çağrılan C/C++ eklentisinin `Segmentation fault` (POSIX `-11` / Windows `0xC0000005` Access Violation) veya `faulthandler` stack trace ile çökmesi durumunda çıkış kodunun açıkça raporlanması.

### Faz 3 — Protokol, Eşzamanlılık ve Çok Dilli (Rust / C++) Sınır Testleri
- [ ] **PT-16 (JSON-RPC 2.0 Framing & Devasa İstek Fuzzing)**: `stdin` üzerinden eksik JSON, 1 MB uzunluğunda komut satırı veya geçersiz UTF-8 içeren JSON-RPC mesajları gönderildiğinde sunucu döngüsünün (`main()`) ayakta kalması.
- [ ] **PT-17 (Hibrit Python + Rust / C++ Derleme Hataları)**: `pip install -e .` veya `maturin develop` sırasında Python sarmalayıcısı içinden patlayan `rustc` / `gcc` / `cl.exe` hatalarının otomatik algılanması.
- [ ] **PT-18 (Salt-Okunur Çalışma Dizini Fallback Testi)**: Yazma izni olmayan bir `workdir` üzerinde çalıştırıldığında logların `~/.gemini/logs/argon_last_run.log` adresine sorunsuz yönlendirilmesi.

---

## 5. Testleri Çalıştırma Komutu

Tüm regresyon, E2E ve Python penetrasyon testlerini tek komutla çalıştırmak için:

```powershell
C:\Tools\Python3.14\python.exe -m unittest discover -s tests -v
```
