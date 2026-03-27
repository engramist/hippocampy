import pypdf
from pypdf.generic import BooleanObject, NameObject, TextStringObject

path = "InvertorsDocs/sb0016-filled.pdf"
out = "InvertorsDocs/sb0016-filled-fixed.pdf"

reader = pypdf.PdfReader(path)
writer = pypdf.PdfWriter()
writer.set_need_appearances_writer(True)

for page in reader.pages:
    writer.add_page(page)

root = reader.trailer["/Root"]
acro = root.get("/AcroForm")
if acro:
    writer._root_object.update({NameObject("/AcroForm"): acro})
    w_acro = writer._root_object["/AcroForm"].get_object()
    w_acro.update({NameObject("/NeedAppearances"): BooleanObject(True)})

problem_fields = {
    "Residence City and either State or Foreign CountryRow1",
    "Address",
    "Country",
    "Email_2",
    "TITLE OF THE INVENTION 500 characters maxRow1",
    "Firm or Individual Name",
}

for page in writer.pages:
    annots = page.get("/Annots")
    if not annots:
        continue
    for annot_ref in annots:
        annot = annot_ref.get_object()
        if annot.get("/FT") != "/Tx":
            continue
        name = annot.get("/T")
        if name in problem_fields:
            annot.update({NameObject("/DA"): TextStringObject("/Helv 8 Tf 0 g")})
            if "/AP" in annot:
                del annot[NameObject("/AP")]

with open(out, "wb") as f:
    writer.write(f)

print(f"Wrote fixed file: {out}")
