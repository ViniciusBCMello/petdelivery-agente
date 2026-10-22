import math

RAIO_TERRA_KM = 6371.0


def distancia_km(lat1, lon1, lat2, lon2):
    """
    Distância em LINHA RETA entre dois pontos (fórmula de Haversine), em km.
    """
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = p2 - p1
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * RAIO_TERRA_KM * math.asin(math.sqrt(a))