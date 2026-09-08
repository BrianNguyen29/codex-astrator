# Codex Astrator

Codex Astrator là payload công khai, đã loại bỏ dữ liệu cá nhân, cho quy trình
Codex ưu tiên ủy quyền. Kho cung cấp một preset tham chiếu với root GPT-6 Astra
và sáu vai trò trung tính cho công việc thường, triển khai phức tạp, khám phá,
kiểm thử, nghiên cứu và review độc lập. Tính sẵn có của model phụ
thuộc host và tài khoản, không được dự án đảm bảo.

Kho này chứa hướng dẫn nguồn và trình cài Python nhỏ. Nó không cài Codex,
model, credential, plugin hay package bên thứ ba. Tài liệu tiếng Anh ở
[README.md](README.md); hướng dẫn chi tiết nằm trong thư mục [docs](docs/).

## Cài đặt an toàn

Yêu cầu Python 3.11 trở lên. Từ thư mục checkout, xem trước cài đặt cho một
project:

```text
python scripts/install.py install --scope project --target PATH
```

Lệnh `install` mặc định chỉ dry-run. Chỉ thêm `--apply` sau khi xem các path sẽ
thay đổi:

```text
python scripts/install.py install --scope project --target PATH --apply
```

Với cài đặt global, dùng `--scope global` và đặt target là thư mục home mong
muốn. Global ghi `.codex/config.toml`, `.codex/AGENTS.md`,
`.codex/agents/`, `.agents/skills/`; project ghi `.codex/`, `.agents/` và
`AGENTS.md` tại root project. Dùng `--source PATH` nếu không tự phát hiện được
root của kho.

File đã tồn tại không bị thay thế ngầm; các cấu hình không thuộc payload được
bảo toàn. Khi dry-run báo collision, cần chỉ rõ `--replace-existing` cùng với
`--apply`. Xem [docs/installation.md](docs/installation.md)
và [docs/permissions.md](docs/permissions.md).

Với bản cài đặt có manifest phiên bản an toàn hiện tại, mọi file được quản lý
phải còn khớp hash đã ghi trước khi lập kế hoạch cập nhật. `--replace-existing`
không bỏ qua kiểm tra drift. Installer chụp trạng thái manifest và mọi đích liên
quan rồi kiểm tra lại ngay trước khi ghi, nhưng không khóa filesystem; tránh
chạy installer hoặc editor khác trong lúc `--apply`.

Nếu phiên bản đã cài có bộ vai trò được quản lý khác, installer sẽ từ chối
nâng cấp kể cả khi dùng `--replace-existing`. Hãy gỡ phiên bản trước, kiểm tra
các file đã khôi phục, rồi cài phiên bản này.

Manifest dùng phiên bản an toàn cũ không được tự động nâng cấp hoặc gỡ, kể cả
khi hash hiện tại vẫn khớp. Cả preview và apply đều giữ nguyên file cùng backup
và yêu cầu người dùng đối chiếu, hòa giải thủ công.

Xem trước hoặc áp dụng gỡ cài đặt:

```text
python scripts/install.py uninstall --scope project --target PATH
python scripts/install.py uninstall --scope project --target PATH --apply
python scripts/install.py --uninstall --scope project --target PATH
```

`doctor` chỉ kiểm tra file và TOML, không cài đặt:

```text
python scripts/doctor.py --source .
```

## Quy trình và giới hạn

Mặc định ủy quyền thực thi và điều tra có nội dung, kể cả thay đổi nhỏ;
chỉ hội thoại thuần túy được trả lời trực tiếp. Công việc thường dùng một
worker cho khám phá, chỉnh sửa và kiểm thử tập trung. Công việc có invariant
chưa chắc chắn, persistence, concurrency, rollback hoặc recovery khó được
chuyển thẳng cho complex worker. Chỉ thêm explorer, tester hoặc researcher khi
bằng chứng độc lập thực sự có ích; dùng reviewer read-only cho rủi ro kiến trúc, bảo mật, migration, quyền,
configuration, policy hoặc compatibility. Tối đa ba child agent hoạt động đồng
thời, hoặc ít hơn theo giới hạn host; child không tạo child khác.

CI hiện chỉ chạy Windows cho đến khi các host khác được kiểm tra. macOS,
Linux và model availability còn chưa xác minh. Đọc
[docs/compatibility.md](docs/compatibility.md) và [docs/token-usage.md](docs/token-usage.md).
Dự án không hứa hẹn tiết kiệm token hay chi phí; hãy tự đo trên workload của
bạn.

## Giấy phép

Kho dùng Apache License 2.0, xem [LICENSE](LICENSE). Một phần material được
phát triển từ [donvito/codex-astra-luna-orchestrator](https://github.com/donvito/codex-astra-luna-orchestrator)
theo Apache-2.0; xem [NOTICE](NOTICE) và các modification notice trong payload.
