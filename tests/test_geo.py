from app.tools.geo import distancia_km


def test_distancia_de_um_ponto_a_ele_mesmo_e_zero():
    assert distancia_km(-22.9, -43.2, -22.9, -43.2) == 0


def test_distancia_e_simetrica():
    ida = distancia_km(-22.8806, -43.3600, -22.9246, -43.2420)
    volta = distancia_km(-22.9246, -43.2420, -22.8806, -43.3600)
    assert ida == volta


def test_distancia_conhecida_rio_sao_paulo():
    # centro do Rio ate o centro de Sao Paulo: cerca de 357 km em linha reta
    d = distancia_km(-22.9068, -43.1729, -23.5505, -46.6333)
    assert 350 < d < 365