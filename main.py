from azure.data.tables import TableServiceClient, UpdateMode
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException, Security, status, Query
from fastapi.security import APIKeyHeader
from typing import Optional
from datetime import datetime, timezone
from dotenv import load_dotenv
import os
import uuid
import logging

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="API Atendimentos Hyper")

CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
TABLE_NAME = os.getenv("AZURE_TABLE_NAME", "renovacaoHyper")
PARTITION_KEY = "HyperFlowRenovacao"

API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)


# ---------- Autenticação ----------
async def get_api_key(api_key: str = Security(api_key_header)):
    expected_key = os.getenv("API_KEY")

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Chave de API não fornecida",
        )

    if api_key != expected_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chave de API inválida",
        )

    return api_key


# ---------- Modelos ----------
class DadosRenovacao(BaseModel):
    """Modelo usado no POST (insert completo)."""
    NomeCliente: str
    Documento: str
    ProtocoloAntigo: str
    Telefone: str
    DataDisparo: str
    AgenteRegistro: str
    MensagemHSM: str
    Produto: str
    Rotulo: str


class AtualizacaoRenovacao(BaseModel):
    """Modelo usado no PATCH (update parcial). Só RowKey é obrigatório."""
    RowKey: str
    NomeCliente: Optional[str] = None
    Documento: Optional[str] = None
    ProtocoloAntigo: Optional[str] = None
    Telefone: Optional[str] = None
    DataDisparo: Optional[str] = None
    AgenteRegistro: Optional[str] = None
    MensagemHSM: Optional[str] = None
    Produto: Optional[str] = None
    Rotulo: Optional[str] = None


class DadosSuporteCliente(BaseModel):
    """Modelo usado no POST (insert completo)."""
    NomeCliente: str
    Documento: str
    Telefone: str
    DataAtendimento: str
    Rotulo: str


class AtualizacaoSuporteCliente(BaseModel):
    """Modelo usado no PATCH (update parcial). Só RowKey é obrigatório."""
    RowKey: str
    NomeCliente: Optional[str] = None
    Documento: Optional[str] = None
    Telefone: Optional[str] = None
    DataAtendimento: Optional[str] = None
    Rotulo: Optional[str] = None



# ---------- Helper ----------
def _get_table_client(nome_tabela):
    if not CONNECTION_STRING:
        raise HTTPException(status_code=500, detail="Connection string não configurada")
    service = TableServiceClient.from_connection_string(conn_str=CONNECTION_STRING)
    # return service.get_table_client(TABLE_NAME)
    return service.get_table_client(nome_tabela)


@app.get(
    "/atendimentos-hyper",
    status_code=200,
    tags=["Atendimentos Hyper"],
    summary="Listar registros de uma tabela",
    description="Lista todos os registros da tabela informada no parâmetro 'tabela'.",
)

def listar_atendimentos(
    tabela: str = Query(
        ...,
        description="Nome da tabela do Azure Table Storage (ex: renovacaoCertificado)",
        examples=["renovacaoCertificado"],
    ),
    api_key: str = Security(get_api_key),
):
    if not CONNECTION_STRING:
        raise HTTPException(status_code=500, detail="Connection string não configurada")

    try:
        service = TableServiceClient.from_connection_string(conn_str=CONNECTION_STRING)
        table = service.get_table_client(tabela)

        registros = list(table.list_entities())

        logger.info(f"Listados {len(registros)} registros da tabela '{tabela}'")
        return {
            "tabela": tabela,
            "total": len(registros),
            "registros": registros,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Erro ao listar registros da tabela '{tabela}'")
        raise HTTPException(status_code=500, detail=f"Erro ao listar: {str(e)}")


# ---------- POST: cria novo registro ----------
@app.post(
    "/renovacao-certificado/insere-atendimento",
    status_code=201,
    tags=["Renovação Hyper"],
    summary="Adiciona o atendimento da hyper no Azure Table",
)
def criar_automacao(
    dados: DadosRenovacao,
    api_key: str = Security(get_api_key),
):
    row_key = str(uuid.uuid4())

    entity = {
        "PartitionKey": PARTITION_KEY,
        "RowKey": row_key,
        "NomeCliente": dados.NomeCliente,
        "Documento": dados.Documento,
        "ProtocoloAntigo": dados.ProtocoloAntigo,
        "Telefone": dados.Telefone,
        "DataDisparo": dados.DataDisparo,
        "AgenteRegistro": dados.AgenteRegistro,
        "MensagemHSM": dados.MensagemHSM,
        "Produto": dados.Produto,
        "Rotulo": dados.Rotulo,
        "TimestampInsercao": datetime.now(timezone.utc).isoformat(),
    }

    try:
        table = _get_table_client("renovacaoHyper")
        table.create_entity(entity=entity)

        logger.info(f"Registro inserido: RowKey={row_key}")
        return {"status": "sucesso", "row_key": row_key}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Erro ao inserir no Azure Table Storage")
        raise HTTPException(status_code=500, detail=f"Erro ao inserir: {str(e)}")


# ---------- PATCH: atualiza registro existente ----------
@app.patch(
    "/renovacao-certificado/atualiza-atendimento",
    status_code=200,
    tags=["Renovação Hyper"],
    summary="Atualiza o atendimento da hyper no Azure Table",
    )
def atualizar_automacao(
    dados: AtualizacaoRenovacao,
    api_key: str = Security(get_api_key),
):
    entity = {
        "PartitionKey": PARTITION_KEY,
        "RowKey": dados.RowKey,
    }

    campos_opcionais = [
        "NomeCliente", "Documento", "ProtocoloAntigo", "Telefone",
        "DataDisparo", "AgenteRegistro", "MensagemHSM", "Produto", "Rotulo",
    ]
    for campo in campos_opcionais:
        valor = getattr(dados, campo)
        if valor is not None:
            entity[campo] = valor

    # Bloqueia update que só manda RowKey (nada para atualizar)
    if len(entity) <= 2:
        raise HTTPException(
            status_code=400,
            detail="Envie ao menos um campo além do RowKey para atualizar",
        )

    entity["TimestampAtualizacao"] = datetime.now(timezone.utc).isoformat()

    try:
        table = _get_table_client("renovacaoHyper")

        # upsert_entity(MERGE): atualiza se existe, cria se não existe
        # Se quiser BLOQUEAR quando não existir, troque por table.update_entity(...)
        table.upsert_entity(entity=entity, mode=UpdateMode.MERGE)

        logger.info(f"Registro atualizado (merge): RowKey={dados.RowKey}")
        return {
            "status": "sucesso",
            "row_key": dados.RowKey,
            "campos_atualizados": list(entity.keys()),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Erro ao atualizar no Azure Table Storage")
        raise HTTPException(status_code=500, detail=f"Erro ao atualizar: {str(e)}")
    




# SUPORTE AO CLIENTE - CERTIFICADO
# ---------- POST: cria novo registro ----------
@app.post(
    "/suporte-certificado/insere-atendimento",
    status_code=201,
    tags=["Suporte ao Cliente - Certificado"],
    summary="Adiciona o atendimento da hyper no Azure Table",
)
def criar_automacao(
    dados: DadosSuporteCliente,
    api_key: str = Security(get_api_key),
):
    row_key = str(uuid.uuid4())

    entity = {
        "PartitionKey": PARTITION_KEY,
        "RowKey": row_key,
        "NomeCliente": dados.NomeCliente,
        "Documento": dados.Documento,
        "Telefone": dados.Telefone,
        "DataAtendimento": dados.DataAtendimento,
        "Rotulo": dados.Rotulo,
        "TimestampInsercao": datetime.now(timezone.utc).isoformat(),
    }

    try:
        table = _get_table_client("suporteCertHyper")
        table.create_entity(entity=entity)

        logger.info(f"Registro inserido: RowKey={row_key}")
        return {"status": "sucesso", "row_key": row_key}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Erro ao inserir no Azure Table Storage")
        raise HTTPException(status_code=500, detail=f"Erro ao inserir: {str(e)}")


# ---------- PATCH: atualiza registro existente ----------
@app.patch(
    "/suporte-certificado/atualiza-atendimento",
    status_code=200,
    tags=["Suporte ao Cliente - Certificado"],
    summary="Atualiza o atendimento da hyper no Azure Table",
    )

def atualizar_automacao(
    dados: AtualizacaoSuporteCliente,
    api_key: str = Security(get_api_key),
):
    entity = {
        "PartitionKey": PARTITION_KEY,
        "RowKey": dados.RowKey,
    }

    campos_opcionais = [
        "NomeCliente", "Documento", "Telefone",
        "DataAtendimento", "Rotulo",
    ]
    for campo in campos_opcionais:
        valor = getattr(dados, campo)
        if valor is not None:
            entity[campo] = valor

    # Bloqueia update que só manda RowKey (nada para atualizar)
    if len(entity) <= 2:
        raise HTTPException(
            status_code=400,
            detail="Envie ao menos um campo além do RowKey para atualizar",
        )

    entity["TimestampAtualizacao"] = datetime.now(timezone.utc).isoformat()

    try:
        table = _get_table_client("suporteCertHyper")

        # upsert_entity(MERGE): atualiza se existe, cria se não existe
        # Se quiser BLOQUEAR quando não existir, troque por table.update_entity(...)
        table.upsert_entity(entity=entity, mode=UpdateMode.MERGE)

        logger.info(f"Registro atualizado (merge): RowKey={dados.RowKey}")
        return {
            "status": "sucesso",
            "row_key": dados.RowKey,
            "campos_atualizados": list(entity.keys()),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Erro ao atualizar no Azure Table Storage")
        raise HTTPException(status_code=500, detail=f"Erro ao atualizar: {str(e)}")