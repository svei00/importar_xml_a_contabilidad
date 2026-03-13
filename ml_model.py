import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
import pickle

def preparar_texto(row):
    return f"{row['concepto']} {row['rfc_emisor']} {row['rfc_receptor']}"

def entrenar(df):
    df["texto"] = df.apply(preparar_texto, axis=1)

    X = df["texto"]
    y = df["cuenta"]

    vectorizer = TfidfVectorizer(max_features=1000)
    X_vec = vectorizer.fit_transform(X)

    model = LogisticRegression(max_iter=1000)
    model.fit(X_vec, y)

    pickle.dump(model, open("modelo.pkl", "wb"))
    pickle.dump(vectorizer, open("vectorizer.pkl", "wb"))

def predecir(concepto, rfc_emisor, rfc_receptor):
    model = pickle.load(open("modelo.pkl", "rb"))
    vectorizer = pickle.load(open("vectorizer.pkl", "rb"))

    texto = f"{concepto} {rfc_emisor} {rfc_receptor}"
    X = vectorizer.transform([texto])

    return model.predict(X)[0]