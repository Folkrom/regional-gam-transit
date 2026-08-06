import h3


def test_h3_is_v4():
    """La API v4 es un requisito duro: v3 usaba polyfill/geo_to_h3."""
    assert int(h3.__version__.split(".")[0]) >= 4
    assert hasattr(h3, "geo_to_cells")


def test_package_importable():
    import rtgam

    assert rtgam.__name__ == "rtgam"
