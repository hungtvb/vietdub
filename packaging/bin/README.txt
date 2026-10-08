Thư mục này chứa ffmpeg + ffprobe để PyInstaller đóng gói kèm vào app
(vietdub.spec sẽ tự nhặt mọi file bắt đầu bằng "ffmpeg"/"ffprobe" ở đây).

TRÊN WINDOWS (máy Tony), trước khi build .exe:
  1. Tải ffmpeg bản Windows "release essentials" tại:
       https://www.gyan.dev/ffmpeg/builds/
     (file zip, vd: ffmpeg-7.x-essentials_build.zip)
  2. Giải nén, vào thư mục bin bên trong, chép 2 file:
       ffmpeg.exe
       ffprobe.exe
     vào đúng thư mục này (packaging/bin/).
  3. Chạy:  pyinstaller packaging/vietdub.spec
  4. App đóng gói xong sẽ có sẵn ffmpeg cạnh VietDub.exe, không cần cài
     thêm hay thêm vào PATH.

TRÊN LINUX (chỉ để validate spec, không phải build chính thức):
  Đặt binary ffmpeg/ffprobe của Linux vào đây nếu muốn test kèm binary,
  hoặc để trống — spec vẫn build được, chỉ in cảnh báo.
