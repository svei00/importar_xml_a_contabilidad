# dashboard.py
import dash
from dash import dcc, html
import plotly.express as px
import pandas as pd
from db import get_conn

def load_data():
    """Extrae los datos limpios desde SQLite para el dashboard."""
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM facturas", conn)
    conn.close()
    return df

def run_dashboard():
    df = load_data()
    
    if df.empty:
        print("⚠️ No hay datos en la base de datos (SQLite) para mostrar en el dashboard.")
        return

    # Limpiar y preparar datos numéricos
    df['total'] = pd.to_numeric(df['total'], errors='coerce').fillna(0)
    
    # Separar facturas por tipo (I = Ingreso, E = Egreso)
    df_ingresos = df[df['tipo'] == 'I']
    df_egresos = df[df['tipo'] == 'E']

    # Inicializar la app Dash
    app = dash.Dash(__name__)

    # --- GRAFICOS PLOTLY ---
    # 1. Gráfico de pastel para los Gastos por Proveedor
    fig_gastos = px.pie(
        df_egresos, 
        values='total', 
        names='nombre_emisor', 
        title='Distribución de Gastos (Egresos) por Proveedor',
        hole=0.4 # Estilo de dona moderna
    )

    # 2. Gráfico de barras para Ingresos
    fig_ingresos = px.bar(
        df_ingresos, 
        x='fecha', 
        y='total', 
        title='Ingresos (Facturación) por Fecha', 
        color='nombre_receptor',
        text_auto='.2s'
    )

    # --- DISEÑO (HTML) ---
    app.layout = html.Div(style={'fontFamily': 'Arial, sans-serif', 'padding': '20px'}, children=[
        html.H1(children='📊 Dashboard Financiero - ContpaqI Automator', style={'textAlign': 'center'}),
        html.P(children='Análisis interactivo de Facturas, Ingresos y Gastos extraídos del SAT.', style={'textAlign': 'center', 'color': '#555'}),
        
        # Contenedor de gráficos (50% de ancho cada uno para verse lado a lado)
        html.Div([
            html.Div([
                dcc.Graph(id='grafico-gastos', figure=fig_gastos)
            ], style={'display': 'inline-block', 'width': '48%', 'verticalAlign': 'top'}),
            
            html.Div([
                dcc.Graph(id='grafico-ingresos', figure=fig_ingresos)
            ], style={'display': 'inline-block', 'width': '48%', 'verticalAlign': 'top'}),
        ])
    ])

    print("🚀 Iniciando Dashboard Interactivo...")
    print("👉 Abre tu navegador web y visita: http://127.0.0.1:8050")
    
    # Ejecutar servidor local
    app.run_server(debug=False)

if __name__ == '__main__':
    run_dashboard()