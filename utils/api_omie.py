import streamlit as st
import requests
import json
import datetime
from  datetime import datetime,timedelta

APP_KEY = st.secrets["APP_KEY"]
APP_SECRET = st.secrets["APP_SECRET"]

ontem = datetime.now() - timedelta(days=1)
ontem_formatado = ontem.strftime("%d/%m/%Y")

#print(ontem_formatado)

def ListarClientes(cnpj_input):
    try:
        URL = "https://app.omie.com.br/api/v1/geral/clientes/"
        payload = {
            "call": "ListarClientes",
            "app_key": APP_KEY,
            "app_secret": APP_SECRET,
            "param": [
                {
                    "pagina": 1,
                    "registros_por_pagina": 50,
                    "clientesFiltro": {
                        "cnpj_cpf": cnpj_input
                    },
                    "exibir_obs": "N"
                }
            ]
        }

        response = requests.post(URL, json=payload)
        retorno = response.json()

        clientes = retorno.get("clientes_cadastro", [])

        if not clientes:
            return None  # ← ESSENCIAL

        cliente = clientes[0]  # assume o primeiro
        codigo_omie = cliente.get("codigo_cliente_omie")
        razao_social = cliente.get("razao_social")

        return codigo_omie, razao_social
    
    except requests.exceptions.RequestException as e:
        return None

def ListarRemessas(codigo_cliente):
    URL = "https://app.omie.com.br/api/v1/produtos/remessa/"
    pagina = 1
    ha_mais_paginas = True
    remessas_dict = {}

    while ha_mais_paginas:
        payload = {
            "call": "ListarRemessas",
            "app_key": APP_KEY,
            "app_secret": APP_SECRET,
            "param": [
                {
                    "nPagina": pagina,
                    "nRegistrosPorPagina": 100,
                    "cExibirDetalhes": "N",
                    "nIdCliente": codigo_cliente,
                    "dtAltDe": ontem_formatado
                }
            ]
        }

        response = requests.post(URL, json=payload)
        data = response.json()

        # Extrai as remessas da página atual
        remessas = data.get("remessas", [])
        if not remessas:
            ha_mais_paginas = False
            break

        for remessa in remessas:
            cabec = remessa.get("cabec", {})
            numero = cabec.get("cNumeroRemessa")
            codigo = cabec.get("nCodRem")
            faturada = cabec.get("faturada")
            if numero and codigo and faturada == "N":
                remessas_dict[str(numero)] = codigo

        # Verifica se ainda há mais páginas
        total_paginas = data.get("nTotPaginas", 1)
        if pagina >= total_paginas:
            ha_mais_paginas = False
        else:
            pagina += 1

    # Log pra debug
    print("\n===== MAPA COMPLETO DE REMESSAS =====")
    for numero, codigo in remessas_dict.items():
        print(f"Remessa Nº {numero}  |  Código: {codigo}")
    print(f"Total de remessas coletadas: {len(remessas_dict)}")
    print("=====================================\n")

    codigo_remessa = remessas_dict

    print(codigo_remessa)

    return codigo_remessa

def ConsultarRemessas(codigo_remessa):
    URL = "https://app.omie.com.br/api/v1/produtos/remessa/"

    payload = {
        "call": "ConsultarRemessa",
        "app_key": APP_KEY,
        "app_secret": APP_SECRET,
        "param": [
            {
                "nCodRem": codigo_remessa
            }
        ]
    }

    response = requests.post(URL, json=payload)
    data = response.json()

    return data

def ConsultarProduto(codigo_produto):
    URL = "https://app.omie.com.br/api/v1/geral/produtos/"
    payload = {
        "call": "ConsultarProduto",
        "app_key": APP_KEY,
        "app_secret": APP_SECRET,
        "param": [
            {
                 "codigo_produto": codigo_produto,
            }
        ]
    }

    response = requests.post(URL,json=payload)
    retorno = response.json()

    produto = retorno.get("descricao")
    sku = retorno.get("codigo")

    return produto,sku

def AlterarRemessa(nCodRem,volume, produtos,nCodCli):
    URL = "https://app.omie.com.br/api/v1/produtos/remessa/"
    payload = {
        "call": "AlterarRemessa",
        "app_key": APP_KEY,
        "app_secret": APP_SECRET,
        "param":[{
            "cabec":{
                "nCodRem":nCodRem,
                "nCodCli":nCodCli
            },
            "frete":{
                "nQtdVol":volume
            },
            "produtos":produtos
        }]
    }

    print("===== JSON ENVIADO =====")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    print("=========================")

    response = requests.post(URL, json=payload)

    if response.status_code == 200:
        print("✅ Sucesso ao alterar remessa!")
        return response.json()
    else:
        print("❌ Erro na requisição:", response.text)
        return None