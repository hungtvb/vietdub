Thư mục này chứa FFmpeg/FFprobe tùy chọn để PyInstaller đóng gói cùng VietDub.
vietdub.spec tự tìm các file có tên bắt đầu bằng ffmpeg hoặc ffprobe.

Build Windows:
1. Tải bản Windows release essentials từ https://www.gyan.dev/ffmpeg/builds/.
2. Giải nén và chép ffmpeg.exe cùng ffprobe.exe vào packaging/bin/.
3. Chạy pyinstaller packaging/vietdub.spec từ thư mục gốc.
4. App onedir nằm trong dist/VietDub; binary FFmpeg được đặt cạnh VietDub.exe.

Nếu thư mục này trống, spec vẫn có thể build nhưng app cần FFmpeg trong PATH
hoặc người dùng phải cấu hình đường dẫn trong Cài đặt.

Build Linux chỉ dùng để kiểm tra spec; Windows là đích đóng gói chính thức.
