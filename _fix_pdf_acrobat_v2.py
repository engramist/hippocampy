import pypdf
from pypdf.generic import NameObject, TextStringObject

src = "InvertorsDocs/sb0016-filled.pdf"
out = "InvertorsDocs/sb0016-filled-acrobat-v2.pdf"

reader = pypdf.PdfReader(src)
writer = pypdf.PdfWriter()
for page in reader.pages:
    writer.add_page(page)

# Carry over AcroForm as-is to preserve existing visible appearances
acro = reader.trailer["/Root"].get("/AcroForm")
if acro:
    writer._root_object.update({NameObject("/AcroForm"): acro})

# Update only values that were clipping in Acrobat.
# Keep these short so existing appearance streams remain fully visible.
field_updates = {
    "Residence City and either State or Foreign CountryRow1": "Sandy, Utah, USA",
    "Country": "USA",
    "TOTAL FEE AMOUNT": "64",
}

for page in writer.pages:
    annots = page.get("/Annots")
    if not annots:
        continue
    for annot_ref in annots:
        annot = annot_ref.get_object()
        name = annot.get("/T")
        if name in field_updates:
            annot.update({NameObject("/V"): TextStringObject(field_updates[name])})
            # Nudge font size down only for fee field in case the source stream is oversized.
            if name == "TOTAL FEE AMOUNT":
                annot.update({NameObject("/DA"): TextStringObject("/Helv 10 Tf 0 g")})

with open(out, "wb") as f:
    writer.write(f)

print(f"Wrote: {out}")
