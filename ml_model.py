# ml_model.py
import os
import pickle
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import OneHotEncoder
from sklearn.linear_model import LogisticRegression
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline


def _model_path(rfc):
    """Un modelo POR EMPRESA: empresas/<RFC>/modelo.pkl (evita contaminación entre clientes)."""
    safe = "".join(c for c in str(rfc) if c.isalnum()) or "GLOBAL"
    d = os.path.join("empresas", safe)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "modelo.pkl")


def build_pipeline():
    # Texto (concepto + proveedor) + Código Postal
    pre = ColumnTransformer(
        transformers=[
            ("txt", TfidfVectorizer(max_features=1000), "texto"),
            ("cp", OneHotEncoder(handle_unknown="ignore"), ["cp"]),
        ]
    )
    clf = LogisticRegression(max_iter=2000)
    return Pipeline(steps=[("pre", pre), ("clf", clf)])


def train(df: pd.DataFrame, rfc):
    if df is None or df.empty:
        print("⚠️ Sin datos de entrenamiento aún")
        return

    df = df.copy()
    df["texto"] = (
        df["concepto"].fillna("") + " " +
        df["proveedor"].fillna("") + " " +
        df["cp"].fillna("")
    ).str.lower()
    df["cp"] = df["cp"].fillna("").astype(str)

    # Se necesitan al menos 2 cuentas distintas para que el clasificador aprenda algo útil
    if df["cuenta"].nunique() < 2:
        print(f"⚠️ Solo hay {df['cuenta'].nunique()} cuenta(s) etiquetada(s); "
              f"se requieren ≥2 clases distintas para entrenar.")
        return

    X = df[["texto", "cp"]]
    y = df["cuenta"]

    pipe = build_pipeline()
    pipe.fit(X, y)

    with open(_model_path(rfc), "wb") as f:
        pickle.dump(pipe, f)
    print(f"✅ Modelo entrenado para {rfc} con {len(df)} ejemplos / {y.nunique()} cuentas.")


def predict(concepto, proveedor, cp, rfc):
    try:
        with open(_model_path(rfc), "rb") as f:
            pipe = pickle.load(f)
    except Exception:
        return None  # sin modelo todavía -> el llamador usa la cuenta por defecto

    df = pd.DataFrame([{
        "texto": (str(concepto) + " " + str(proveedor) + " " + str(cp)).lower(),
        "cp": str(cp),
    }])
    try:
        return pipe.predict(df)[0]
    except Exception:
        return None
