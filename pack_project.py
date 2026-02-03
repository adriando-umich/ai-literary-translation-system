import os
from datetime import datetime  # <--- 1. Import thêm cái này

# <--- 2. Tạo timestamp hiện tại (VD: 20231025_120000)
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

# <--- 3. Gắn timestamp vào tên file
OUTPUT_FILE = f"project_context_{timestamp}.txt"

# Các thư mục/file cần BỎ QUA (không quét)
IGNORE_DIRS = {'.git', '__pycache__', 'venv', 'env', '.idea', '.vscode', 'build', 'dist', 'node_modules'}
IGNORE_FILES = {'.DS_Store', 'project_context.txt', 'pack_project.py', '.gitignore'}
# Chỉ lấy các đuôi file code (tuỳ bạn chỉnh)
ALLOWED_EXT = {'.py', '.html', '.css', '.js', '.json', '.md', '.txt'}


def pack_project():
    # Thêm dòng này để loại bỏ chính file output vừa tạo ra khỏi danh sách quét (tránh lỗi đệ quy)
    IGNORE_FILES.add(OUTPUT_FILE)

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as outfile:
        # Duyệt qua tất cả thư mục và file
        for root, dirs, files in os.walk("."):
            # Lọc bỏ các thư mục không cần thiết
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]

            for file in files:
                if file in IGNORE_FILES:
                    continue

                # Bỏ qua các file project_context cũ (có timestamp khác) để đỡ nặng
                if file.startswith("project_context_") and file.endswith(".txt"):
                    continue

                # Kiểm tra đuôi file
                ext = os.path.splitext(file)[1]
                if ext not in ALLOWED_EXT:
                    continue

                file_path = os.path.join(root, file)

                # Ghi tiêu đề file
                outfile.write(f"\n{'=' * 50}\n")
                outfile.write(f"FILE: {file_path}\n")
                outfile.write(f"{'=' * 50}\n")

                # Ghi nội dung file
                try:
                    with open(file_path, 'r', encoding='utf-8') as infile:
                        outfile.write(infile.read())
                except Exception as e:
                    outfile.write(f"[Error reading file: {e}]")

                outfile.write("\n")

    print(f"Đã gom toàn bộ code vào file: {OUTPUT_FILE}")


if __name__ == "__main__":
    pack_project()