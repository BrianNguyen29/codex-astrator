# Codex Astrator

**Payload orchestration ưu tiên ủy quyền, có thể review cho Codex.**

Codex Astrator cung cấp cho project Codex một mô hình root/child rõ ràng, sáu
vai trò được đặt tên và trình cài Python theo nguyên tắc xem trước trước khi
ghi. Ranh giới ủy quyền, thiết lập model và phạm vi ghi nằm trong các file có
thể kiểm tra và quản lý bằng version control. Đây là source distribution đã
được làm sạch, không phải dịch vụ hosted.

[![Validate](https://github.com/BrianNguyen29/codex-astrator/actions/workflows/validate.yml/badge.svg)](https://github.com/BrianNguyen29/codex-astrator/actions/workflows/validate.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Apache License 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

[English](README.md) · [Tiếng Việt](README.vi.md)

> Trạng thái: `v0.1.0` đang được lên kế hoạch và vẫn là pre-release; chưa
> phát hành.

## Vì sao dùng Codex Astrator?

- Xác định rõ root chịu trách nhiệm diễn giải, phân quyền, tích hợp, nghiệm
  thu và báo cáo cuối.
- Điều hướng triển khai thường ngày, recovery khó, khám phá, nghiên cứu,
  kiểm thử và review độc lập đến các role có access mode minh bạch.
- Xem kế hoạch cài đặt trước khi thay đổi project đích, đồng thời bảo toàn các
  thiết lập nằm ngoài path do payload quản lý.
- Giữ lớp orchestration công khai, tool-neutral, không chứa credential, dữ liệu
  session hay cấu hình gắn với máy cụ thể.

## Thành phần

```text
payload/
  agents/                         sáu role TOML có tên
  skills/astra-orchestrator/      quy tắc ủy quyền và điều hướng
  instructions/                   hướng dẫn orchestration project/global
profiles/reference.toml           một reference preset công khai
docs/                             kiến trúc, cài đặt, an toàn và giới hạn
scripts/install.py                CLI cài/cập nhật và gỡ cài đặt
scripts/doctor.py                 bộ kiểm tra payload và TOML tĩnh
tests/                            test installer tập trung
```

Payload có thể cài đặt tách biệt với `AGENTS.md` dành cho contributor của
repository này: file đó điều chỉnh đóng góp tại đây; instruction trong payload
điều chỉnh project Codex đích sau khi cài.

## Reference preset

Repository cung cấp một reference preset duy nhất. Preset bật multi-agent và
cho phép tối đa ba child thread trong mỗi session. Hãy xác nhận model và tính
năng được host, tài khoản đích hỗ trợ.

Preset cũng bật tùy chọn experimental context-management bằng table
`[features.context_management]` và `experimental_mode = true`. Client OpenAI
mặc định tắt tùy chọn này; hãy xác minh client và tài khoản đích đủ điều kiện
trước khi dựa vào nó. Context management experimental không bảo đảm hiệu năng
hay tiết kiệm token.

Preset của root yêu cầu context window 400.000 token và tự động compact ở
250.000 token, theo tổng usage. Đây là các giá trị cấu hình phía client; chúng
không bảo đảm giới hạn input phía server hay tiết kiệm token. Hãy xác nhận
host đích hỗ trợ các giá trị này.

| Role | Model | Effort | Access | Trách nhiệm |
| --- | --- | --- | --- | --- |
| Root | `gpt-6-astra` | `low` | theo host | Quyết định, tích hợp, xác minh |
| `explorer` | `gpt-5.6-luna` | `low` | read-only | Tìm path, flow và test |
| `worker` | `gpt-5.6-luna` | `xhigh` | workspace-write | Triển khai thường ngày có giới hạn |
| `complex_worker` | `gpt-5.6-sol` | `medium` | workspace-write | Invariant chưa chắc chắn, persistence, concurrency, rollback, recovery |
| `tester` | `gpt-5.6-luna` | `medium` | workspace-write | Tái hiện và xác minh hành vi |
| `researcher` | `gpt-5.6-luna` | `medium` | read-only | Trả lời câu hỏi kỹ thuật có giới hạn |
| `reviewer` | `gpt-6-astra` | `low` | read-only | Đánh giá độc lập các rủi ro đáng kể |

## Bắt đầu nhanh

Yêu cầu Python 3.11 trở lên.

```bash
git clone https://github.com/BrianNguyen29/codex-astrator.git
cd codex-astrator
```

Xem trước cài đặt theo project. Lệnh mặc định chỉ đọc:

```bash
python scripts/install.py install --scope project --target "PATH/TO/YOUR_PROJECT"
```

Kiểm tra kế hoạch rồi mới áp dụng có chủ đích:

```bash
python scripts/install.py install --scope project --target "PATH/TO/YOUR_PROJECT" --apply
```

Để xem trước cài global, đặt target là thư mục home mong muốn.
Chỉ thêm `--apply` sau khi kiểm tra phạm vi ảnh hưởng rộng hơn:

```bash
python scripts/install.py install --scope global --target "PATH/TO/YOUR_HOME"
```

Dùng `--source PATH` khi chạy installer từ ngoài checkout. Khi gỡ cài đặt,
hãy xem trước rồi chỉ thêm `--apply` sau khi kiểm tra các path được sở hữu;
xem đầy đủ contract lệnh trong [Installation](docs/installation.md).

Vòng lặp vận hành là:

`root quyết định → child thực hiện phần việc có giới hạn → bằng chứng → root tích hợp và xác minh`

## An toàn và ranh giới

- Manifest v3 bảo toàn POSIX mode trong phạm vi hỗ trợ và dùng quyền backup
  riêng tư. Khôi phục manifest v1/v2 cần đối chiếu thủ công. Backup/restore ACL
  của file đã tồn tại trên Windows chưa được hỗ trợ và bị từ chối an toàn;
  xem [giới hạn quyền](docs/permissions.md#filesystem-permission-limits).
- File đích đã tồn tại sẽ được báo là collision và không bao giờ tự động bị
  thay thế. Chỉ dùng `--replace-existing` cùng `--apply` sau khi kiểm tra các
  path cụ thể.
- Manifest phiên bản hiện tại từ chối update nếu file được theo dõi đã drift,
  kể cả khi có `--replace-existing`. Apply có thay đổi phối hợp qua lock
  cooperative theo từng target tại `.codex/.astrator.lock`, giữ đến khi commit
  hoặc rollback; snapshot vẫn cần thiết vì editor bên ngoài không tham gia lock
  và có thể race sau lần kiểm tra cuối.
- Manifest safety-version cũ không được tự động nâng cấp hoặc xóa. File và
  backup vẫn nguyên vẹn cho đến khi đối chiếu thủ công.
- Khi bộ role được quản lý thay đổi, cần gỡ phiên bản trước, kiểm tra các
  file đã khôi phục rồi mới cài phiên bản mới.
- Apply có cơ chế rollback. Nếu ghi hoặc rollback thất bại, transaction backup
  được giữ lại và có thể cần recovery thủ công.
- Installer không cài Codex, model, plugin, package hay credential; xác thực,
  API, publish, deploy, commit và push nằm ngoài ranh giới của nó.

Xem [chi tiết cài đặt và recovery](docs/installation.md) cùng
[ranh giới quyền](docs/permissions.md).

## Tương thích và xác minh

Source và installer yêu cầu Python 3.11+. [GitHub Actions workflow](.github/workflows/validate.yml)
trong repository kiểm tra độc lập việc parse source, layout và test tập trung
trên Windows, Ubuntu và macOS với Python 3.11, cộng thêm một job Ubuntu với
Python 3.12 (`fail-fast: false`, tổng cộng bốn job). Một [lần chạy đã quan sát
ở đúng revision hardening `9515d86`](https://github.com/BrianNguyen29/codex-astrator/actions/runs/34341342685)
đã pass cả bốn job. Điều này xác nhận matrix hosted cho commit đó nhưng không
chứng minh Codex runtime thực tương thích hay hoàn tất các release gate khác.
Workflow cũng không chạy trên Codex host thực. Test preview/apply tập trung
chỉ dùng target disposable và không bao phủ quyền trên target thực. Model cụ
thể phụ thuộc host và tài khoản đích. Smoke test tùy chọn chỉ dùng project
disposable; không kiểm tra role read-only trên file project thực.

Dự án không hứa hẹn tiết kiệm token hay giảm chi phí. Hãy đo workload tiêu
biểu theo hướng dẫn tại [Token usage](docs/token-usage.md).

Chạy các kiểm tra tập trung từ root repository:

```bash
python -m unittest discover -s tests -p "test_*.py"
python scripts/doctor.py --source .
```

## Tài liệu và đóng góp

- [Architecture](docs/architecture.md) — topology, ownership và routing
- [Installation](docs/installation.md) — lệnh, mapping, recovery và xử lý sự cố
- [Permissions](docs/permissions.md) — ranh giới ghi và phê duyệt
- [Compatibility](docs/compatibility.md) — ma trận và quy trình smoke runtime tùy chọn
- [Token usage](docs/token-usage.md) — cách đo và giới hạn
- [Evaluation](docs/evaluation.md) — harness local, kế hoạch giới hạn và kết quả thử nghiệm
- [Release checklist](docs/release-checklist.md) — cổng pre-release `v0.1.0` dự kiến
- [Changelog](CHANGELOG.md) — thay đổi đã xác minh và đang chờ
- [Security](SECURITY.md) — báo cáo lỗ hổng riêng tư và báo cáo an toàn
- [Orchestrator skill](payload/skills/astra-orchestrator/SKILL.md) — quy tắc routing đầy đủ

Hoan nghênh đóng góp. Hãy giữ payload đã được làm sạch, bảo toàn thay đổi
không liên quan, đồng bộ thiết lập role giữa source và tài liệu, đồng thời giữ
thông tin giấy phép chính xác.

## Giấy phép

Phân phối theo [Apache License 2.0](LICENSE). Xem [NOTICE](NOTICE).
