"""Cięcie wycinków (G2.4.2): układ współrzędnych i granica katalogu blobów.

Ramka jedzie z warstwy pozycyjnej, gdzie `top`/`bottom` liczy się od GÓRY strony,
a pdfium chce marginesów od krawędzi. Pomylenie tych dwóch układów daje wycinek,
który wygląda sensownie i pokazuje nie ten fragment — dlatego sprawdza się go
w pikselach, a nie okiem.
"""

from __future__ import annotations

import pytest

from pdf import crop as crop_pdf

pytest.importorskip("pypdfium2")
import pypdfium2 as pdfium

# Strona jest biała poza czarnym pasem przy GÓRNEJ krawędzi. Pusta strona nie
# nadaje się na fixture: wycinek z góry i z dołu miałby wtedy identyczne piksele,
# więc test przechodziłby także przy odwróconym układzie współrzędnych.
CZARNY_PAS_WYSOKOSC = 100


@pytest.fixture
def strona(tmp_path):
    """Strona A4 z czarnym pasem u góry — do sprawdzenia, gdzie trafia ramka."""
    from PIL import Image

    document = pdfium.PdfDocument.new()
    page = document.new_page(595.0, 842.0)
    obraz = pdfium.PdfImage.new(document)
    obraz.set_bitmap(pdfium.PdfBitmap.from_pil(Image.new("RGB", (8, 8), (0, 0, 0))))
    # Matryca pdfium liczy od DOŁU strony, stąd przesunięcie o wysokość minus pas.
    obraz.set_matrix(pdfium.PdfMatrix().scale(595, CZARNY_PAS_WYSOKOSC)
                     .translate(0, 842 - CZARNY_PAS_WYSOKOSC))
    page.insert_obj(obraz)
    page.gen_content()
    path = tmp_path / "arkusz.pdf"
    document.save(str(path))
    document.close()
    return path


def _jasnosc(path) -> float:
    """Średnia jasność wycinka: 0 to czerń, 255 to biel."""
    from PIL import Image

    with Image.open(path) as image:
        szare = image.convert("L")
        return sum(szare.get_flattened_data()) / (szare.size[0] * szare.size[1])


def test_wycinek_ma_wymiary_ramki(strona, tmp_path, monkeypatch):
    monkeypatch.setenv("BLOB_ROOT", str(tmp_path / "blob"))

    out = crop_pdf.crop(strona, 1, (100.0, 50.0, 300.0, 150.0), "test/z1-0.png")

    from PIL import Image
    with Image.open(out) as image:
        # Tolerancja 1 piksela: pdfium zaokrągla wymiar bitmapy po swojemu,
        # a sprawdzane jest to, że ramka trafia w skalę, nie arytmetyka pdfium.
        assert image.size[0] == pytest.approx(200 * crop_pdf.SCALE, abs=1)
        assert image.size[1] == pytest.approx(100 * crop_pdf.SCALE, abs=1)


def test_ramka_liczy_sie_od_gory_strony(strona, tmp_path, monkeypatch):
    """`top = 0` to GÓRA strony, jak w warstwie pozycyjnej — nie dół, jak w pdfium.

    Przy odwróconym układzie wycinek nadal ma poprawny rozmiar i wygląda
    wiarygodnie, tylko pokazuje nie ten fragment arkusza. Dlatego sprawdza się
    piksele: pas u góry jest czarny, ten sam pas u dołu — biały.
    """
    monkeypatch.setenv("BLOB_ROOT", str(tmp_path / "blob"))

    gora = crop_pdf.crop(strona, 1, (0.0, 0.0, 595.0, 100.0), "test/gora.png")
    dol = crop_pdf.crop(strona, 1, (0.0, 742.0, 595.0, 842.0), "test/dol.png")

    assert _jasnosc(gora) < 10
    assert _jasnosc(dol) > 245


def test_pusta_ramka_i_ramka_poza_strona_sa_bledem(strona, tmp_path, monkeypatch):
    monkeypatch.setenv("BLOB_ROOT", str(tmp_path / "blob"))

    with pytest.raises(crop_pdf.CropError, match="pusta"):
        crop_pdf.crop(strona, 1, (300.0, 50.0, 100.0, 150.0), "test/zla.png")
    with pytest.raises(crop_pdf.CropError, match="poza stronę"):
        crop_pdf.crop(strona, 1, (0.0, 0.0, 900.0, 150.0), "test/zla.png")
    with pytest.raises(crop_pdf.CropError, match="poza dokumentem"):
        crop_pdf.crop(strona, 7, (0.0, 0.0, 100.0, 100.0), "test/zla.png")


def test_sciezka_nie_wychodzi_poza_bloby(tmp_path, monkeypatch):
    """`asset.path` bierze się z nazw plików CKE — `..` nie jest scenariuszem z bajki."""
    monkeypatch.setenv("BLOB_ROOT", str(tmp_path / "blob"))

    with pytest.raises(crop_pdf.CropError, match="poza katalog"):
        crop_pdf.target_path("../../gdzie-indziej.png")
    assert crop_pdf.target_path("OMAP/2025-05-14/100/X/z1-0.png").parent.name == "X"
