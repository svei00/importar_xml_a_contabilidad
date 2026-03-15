# ml_model.py
import pickle
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import OneHotEncoder
from sklearn.linear_model import LogisticRegression
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline

MODEL_FILE = "modelo.pkl"

def build_pipeline():
    # Texto + CP
    pre = ColumnTransformer(
        transformers=[
            ("txt", TfidfVectorizer(max_features=1000), "texto"),
            ("cp", OneHotEncoder(handle_unknown="ignore"), ["cp"]),
        ]
    )
    clf = LogisticRegression(max_iter=2000)
    pipe = Pipeline(steps=[("pre", pre), ("clf", clf)])
    return pipe

def train(df: pd.DataFrame):
    if df is None or df.empty:
        print("⚠️ Sin datos de entrenamiento aún")
        return

    df["texto"] = (
        df["concepto"].fillna("") + " " +
        df["proveedor"].fillna("") + " " +
        df["cp"].fillna("")
    ).str.lower()

    X = df[["texto", "cp"]]
    y = df["cuenta"]  # modelo para cuenta

    pipe = build_pipeline()
    pipe.fit(X, y)

    with open(MODEL_FILE, "wb") as f:
        pickle.dump(pipe, f)

    print("✅ Modelo entrenado")
    

def predict(concepto, proveedor, cp):
    try:
        with open(MODEL_FILE, "rb") as f:
            pipe = pickle.load(f)
    except:
        return None  # fallback a reglas

    df = pd.DataFrame([{
        "texto": (concepto + " " + proveedor).lower(),
        "cp": cp
    }])
    return pipe.predict(df)[0]

