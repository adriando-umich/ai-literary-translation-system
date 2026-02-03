# epub/epub_writer.py
import os
import ebooklib
from ebooklib import epub
from utils.logger import log


def write_epub(output_path, book):


    # 1. Định nghĩa file CSS
    css_filename = "styles/bi.css"

    style = epub.EpubItem(
        uid="style_bilingual",
        file_name=css_filename,
        media_type="text/css",
        content="""
/* Đoạn tiếng Anh: Làm mờ nhẹ để nổi bật tiếng Việt */
.bi-en {
    color: #000000;
    margin-bottom: 4px;
    display: block;
}

/* Đoạn tiếng Việt: Xanh, Thụt lề, Có đường kẻ trái */
.bi-vi {
    /* 1. MÀU SẮC */
    color: #555555 !important; 
    
    /* 2. ĐƯỜNG KẺ (LINE LỀ TRÁI) */
    border-left: 3px solid #dddddd !important;

    /* 3. THỤT LỀ & KHOẢNG CÁCH */
    margin-left: 15px !important;  /* Thụt lề trái toàn khối */
    padding-left: 12px !important; /* Khoảng cách từ chữ đến đường kẻ */
    
    margin-top: 5px;
    margin-bottom: 15px;
    display: block;
    line-height: 1.6;
}
"""
    )
    book.add_item(style)

    # 2. Attach CSS to every HTML document (Logic sửa đường dẫn tương đối)
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            # Lấy tên file hiện tại (ví dụ: Text/chap1.xhtml)
            html_path = item.get_name()

            # Lấy thư mục chứa file HTML (ví dụ: Text)
            base_dir = os.path.dirname(html_path)

            # Tính đường dẫn từ HTML tới CSS (ví dụ: ../styles/bi.css)
            relative_css_path = os.path.relpath(css_filename, base_dir)

            # Đổi dấu \ thành / (fix cho Windows)
            relative_css_path = relative_css_path.replace("\\", "/")

            item.add_link(
                href=relative_css_path,
                rel="stylesheet",
                type="text/css"
            )

    # 3. Write EPUB
    epub.write_epub(output_path, book)
    log(f"EPUB WRITTEN: {output_path}")