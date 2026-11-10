# Textbooks

Put the textbook PDFs here. They are **not** in the git repository because
they are copyrighted; this folder is git-ignored except for this file.

`books.json` (in the project root) says which file belongs to which grade and
where each unit and section starts. The demo uses:

| File name expected here | Book | Where to get it |
| --- | --- | --- |
| `grade7-mathematics-new-curriculum.pdf` | Mathematics Student Textbook, Grade 7 (new curriculum, Addis Ababa City Administration Education Bureau) | [kehulum.com](https://kehulum.com/student-textbook/new/grade-7/mathematics) |
| `camara-MathSBG8.pdf` | Mathematics Student Textbook, Grade 8 (Ministry of Education, GEQIP edition; units 1–3) | [Camara Ethiopia resources](https://camaraethiopia.org.et/Addis%20Ababa/CEE_MoE_Resources/content/Maths/Primary/MathSBG8.pdf) |

Download them with:

```bash
curl -L -o textbooks/grade7-mathematics-new-curriculum.pdf \
  "https://kehulum.com/books_asset/books_89/collection/grade-7-mathematics-new-curriculum--student-textbook-kehulumcom1753014402b995.pdf"
curl -L -o textbooks/camara-MathSBG8.pdf \
  "https://camaraethiopia.org.et/Addis%20Ababa/CEE_MoE_Resources/content/Maths/Primary/MathSBG8.pdf"
```

To add another book, put its PDF here and add an entry to `books.json` with
its units, sections and printed start pages (from the book's table of
contents), and `page_offset` = PDF page number − printed page number.
Then run `scripts/setup.sh` again.
