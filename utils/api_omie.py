import streamlit as st
import requests
import json
import time
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict, Any

APP_KEY = st.secrets["APP_KEY"]
APP_SECRET = st.secrets["APP_SECRET"]


ontem = datetime.now() - timedelta(days=10)
ontem_formatado = ontem.strftime("%d/%m/%Y")

# ==============================================================================
# SISTEMA DE CACHE (60 segundos conforme orientação Omie)
# ==============================================================================
class CacheOmie:
    """Cache com TTL de 60 segundos para evitar requisições redundantes"""
    
    def __init__(self, ttl_seconds: int = 60):
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.ttl = ttl_seconds
    
    def get(self, key: str) -> Optional[Any]:
        """Busca item no cache se ainda válido"""
        if key in self.cache:
            item = self.cache[key]
            if datetime.now() < item['expires_at']:
                print(f"   💾 Cache HIT: {key}")
                return item['data']
            else:
                print(f"   ⏰ Cache EXPIRADO: {key}")
                del self.cache[key]
        return None
    
    def set(self, key: str, data: Any):
        """Salva item no cache com TTL"""
        self.cache[key] = {
            'data': data,
            'expires_at': datetime.now() + timedelta(seconds=self.ttl)
        }
        print(f"   💾 Cache SET: {key} (expira em {self.ttl}s)")
    
    def clear(self):
        """Limpa todo o cache"""
        self.cache.clear()
        print("   🗑️  Cache limpo completamente")

# Instância global do cache
_cache = CacheOmie(ttl_seconds=60)

# ==============================================================================
# CONTROLE DE RATE LIMIT
# ==============================================================================
class RateLimiter:
    """Controla rate limit por método conforme limites do Omie"""
    
    def __init__(self):
        # Controle por método: última chamada e contador de requisições por minuto
        self.last_call: Dict[str, datetime] = {}
        self.call_count: Dict[str, int] = {}
        self.window_start: Dict[str, datetime] = {}
        
        # Limites por método (240 req/min por IP + App Key + Método)
        self.max_calls_per_minute = 200  # Margem de segurança (limite real: 240)
        self.min_delay_between_calls = 0.8  # 800ms entre chamadas do mesmo método (SEGURANÇA)
    
    def wait_if_needed(self, method: str):
        """Aguarda se necessário para respeitar rate limit"""
        now = datetime.now()
        
        # Inicializa controles para novo método
        if method not in self.last_call:
            self.last_call[method] = now
            self.call_count[method] = 0
            self.window_start[method] = now
            return
        
        # Reset contador se passou 1 minuto
        if (now - self.window_start[method]).total_seconds() >= 60:
            self.call_count[method] = 0
            self.window_start[method] = now
        
        # Verifica se atingiu limite por minuto
        if self.call_count[method] >= self.max_calls_per_minute:
            wait_time = 60 - (now - self.window_start[method]).total_seconds()
            if wait_time > 0:
                print(f"   ⏸️  Rate limit atingido para {method}. Aguardando {wait_time:.1f}s...")
                time.sleep(wait_time)
                self.call_count[method] = 0
                self.window_start[method] = datetime.now()
        
        # Delay mínimo entre chamadas do mesmo método
        time_since_last = (now - self.last_call[method]).total_seconds()
        if time_since_last < self.min_delay_between_calls:
            sleep_time = self.min_delay_between_calls - time_since_last
            print(f"   ⏱️  SLEEP: {sleep_time:.2f}s (delay entre {method})")
            time.sleep(sleep_time)
        else:
            print(f"   ✅ Tempo desde última chamada: {time_since_last:.2f}s (OK)")
        
        self.last_call[method] = datetime.now()
        self.call_count[method] += 1

# Instância global do rate limiter
_rate_limiter = RateLimiter()

# ==============================================================================
# RETRY COM BACKOFF EXPONENCIAL
# ==============================================================================
def api_call_with_retry(
    url: str,
    payload: dict,
    method_name: str,
    max_retries: int = 3
) -> dict:
    """
    Faz chamada à API com retry e backoff exponencial
    
    Args:
        url: URL da API
        payload: Payload da requisição
        method_name: Nome do método (para rate limit e cache)
        max_retries: Número máximo de tentativas
    
    Returns:
        Resposta JSON da API
    """
    
    for attempt in range(max_retries):
        try:
            # Aplica rate limit antes de chamar
            _rate_limiter.wait_if_needed(method_name)
            
            # Faz a requisição
            response = requests.post(url, json=payload, timeout=30)
            retorno = response.json()
            
            # Verifica se é erro de rate limit (código 6 = REDUNDANT, código 429 = Too Many Requests)
            if isinstance(retorno, list) and len(retorno) > 0:
                erro = retorno[0]
                if erro.get("CODIGO") in [6, 429]:
                    mensagem = erro.get("MENSAGEM", "")
                    print(f"\n⚠️  Erro Omie (tentativa {attempt + 1}/{max_retries}): {mensagem}")
                    
                    if attempt < max_retries - 1:
                        # Backoff exponencial: 2^attempt segundos
                        wait_time = 2 ** attempt
                        print(f"   ⏳ Aguardando {wait_time}s antes de tentar novamente...")
                        time.sleep(wait_time)
                        continue
                    else:
                        print(f"   ❌ Máximo de tentativas atingido")
                        return retorno
            
            # Se chegou aqui, deu certo
            # 🔥 SLEEP OBRIGATÓRIO após cada chamada bem-sucedida
            print(f"   💤 SLEEP: 0.80s (pós-requisição)")
            time.sleep(0.8)  # 500ms após cada requisição
            return retorno
            
        except requests.exceptions.Timeout:
            print(f"   ⏱️  Timeout na tentativa {attempt + 1}/{max_retries}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
        
        except Exception as e:
            print(f"   ❌ Erro na tentativa {attempt + 1}/{max_retries}: {str(e)}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
    
    return {}

# ==============================================================================
# FUNÇÕES DA API OMIE
# ==============================================================================

def ListarClientes(cnpj_input: str) -> Optional[Tuple[int, str]]:
    """Lista clientes por CNPJ"""
    cache_key = f"cliente_{cnpj_input}"
    
    # Verifica cache
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached
    
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

        retorno = api_call_with_retry(URL, payload, "ListarClientes")
        clientes = retorno.get("clientes_cadastro", [])

        if not clientes:
            return None

        cliente = clientes[0]
        codigo_omie = cliente.get("codigo_cliente_omie")
        razao_social = cliente.get("razao_social")
        
        resultado = (codigo_omie, razao_social)
        
        # Salva no cache
        _cache.set(cache_key, resultado)
        
        return resultado
    
    except Exception as e:
        print(f"❌ Erro ao listar clientes: {str(e)}")
        return None


def ListarRemessas(codigo_cliente: int) -> Dict[str, int]:
    """Lista remessas não faturadas de um cliente"""
    cache_key = f"remessas_{codigo_cliente}"
    
    # Verifica cache
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached
    
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
                    "nRegistrosPorPagina": 100,  # Máximo recomendado pelo Omie
                    "cExibirDetalhes": "N",
                    "nIdCliente": codigo_cliente,
                    "dtAltDe": ontem_formatado

                }
            ]
        }

        retorno = api_call_with_retry(URL, payload, "ListarRemessas")
        
        # Verifica se deu erro
        if isinstance(retorno, list) and len(retorno) > 0 and "CODIGO" in retorno[0]:
            break
        
        remessas = retorno.get("remessas", [])
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

        total_paginas = retorno.get("nTotPaginas", 1)
        if pagina >= total_paginas:
            ha_mais_paginas = False
        else:
            pagina += 1

    print(f"\n📦 Total de remessas coletadas: {len(remessas_dict)}")
    
    # Salva no cache
    _cache.set(cache_key, remessas_dict)
    
    return remessas_dict


def ConsultarRemessas(codigo_remessa: int) -> dict:
    """Consulta detalhes de uma remessa"""
    cache_key = f"remessa_{codigo_remessa}"
    
    # Verifica cache
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached
    
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

    retorno = api_call_with_retry(URL, payload, "ConsultarRemessa")
    
    # Salva no cache
    _cache.set(cache_key, retorno)
    
    return retorno


def ConsultarProduto(codigo_produto: int) -> Tuple[Optional[str], Optional[str]]:
    """Consulta dados de um produto"""
    cache_key = f"produto_{codigo_produto}"
    
    # Verifica cache
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached
    
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

    try:
        retorno = api_call_with_retry(URL, payload, "ConsultarProduto")
        
        # Verifica se tem erro na resposta
        if isinstance(retorno, list) and len(retorno) > 0:
            if "CODIGO" in retorno[0] or "faultcode" in retorno[0]:
                print(f"❌ Erro ao consultar produto {codigo_produto}")
                print(json.dumps(retorno, indent=2, ensure_ascii=False))
                return None, None
        
        # Verifica se tem faultstring
        if "faultstring" in retorno:
            print(f"❌ Erro Omie: {retorno.get('faultstring')}")
            return None, None

        produto = retorno.get("descricao")
        sku = retorno.get("codigo")
        
        resultado = (produto, sku)
        
        # Salva no cache
        _cache.set(cache_key, resultado)
        
        return resultado
        
    except Exception as e:
        print(f"❌ Exceção ao consultar produto {codigo_produto}: {str(e)}")
        return None, None


def AlterarRemessa(nCodRem: int, volume: int, produtos: list, nCodCli: int) -> Optional[dict]:
    """Altera dados de uma remessa"""
    URL = "https://app.omie.com.br/api/v1/produtos/remessa/"
    payload = {
        "call": "AlterarRemessa",
        "app_key": APP_KEY,
        "app_secret": APP_SECRET,
        "param": [{
            "cabec": {
                "nCodRem": nCodRem,
                "nCodCli": nCodCli
            },
            "frete": {
                "nQtdVol": volume
            },
            "produtos": produtos
        }]
    }

    print("\n===== JSON ENVIADO =====")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    print("=========================")

    try:
        retorno = api_call_with_retry(URL, payload, "AlterarRemessa")
        
        if isinstance(retorno, list) and len(retorno) > 0 and "CODIGO" in retorno[0]:
            print("❌ Erro ao alterar remessa:")
            print(json.dumps(retorno, indent=2, ensure_ascii=False))
            return None
        
        print("✅ Remessa alterada com sucesso!")
        
        # Limpa cache da remessa alterada
        cache_key = f"remessa_{nCodRem}"
        if cache_key in _cache.cache:
            del _cache.cache[cache_key]
        
        return retorno
        
    except Exception as e:
        print(f"❌ Erro na requisição: {str(e)}")
        return None


def limpar_cache():
    """Limpa todo o cache (útil para forçar atualização)"""
    _cache.clear()