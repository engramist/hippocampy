import pypdf

print("=== sb0016-filled.pdf ===")
r = pypdf.PdfReader("InvertorsDocs/sb0016-filled.pdf")
print(f"Pages: {len(r.pages)}")
for pn, pg in enumerate(r.pages):
    if "/Annots" in pg:
        for a in pg["/Annots"]:
            o = a.get_object()
            fn = o.get("/T", "")
            fv = o.get("/V", "")
            av = o.get("/AS", "")
            if fv or av:
                print(f"  P{pn+1}: [{fn}] = [{fv}] AS=[{av}]")

print()
print("=== sb0015a-filled.pdf ===")
r2 = pypdf.PdfReader("InvertorsDocs/sb0015a-filled.pdf")
print(f"Pages: {len(r2.pages)}")
for pn, pg in enumerate(r2.pages):
    if "/Annots" in pg:
        for a in pg["/Annots"]:
            o = a.get_object()
            fn = o.get("/T", "")
            fv = o.get("/V", "")
            av = o.get("/AS", "")
            if fv or av:
                print(f"  P{pn+1}: [{fn}] = [{fv}] AS=[{av}]")
