# Recife Calor

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)](requirements-processing.txt)
[![Flask](https://img.shields.io/badge/Flask-API-000000?style=flat-square&logo=flask)](app.py)
[![Leaflet](https://img.shields.io/badge/Leaflet-Mapas-397821?style=flat-square&logo=leaflet&logoColor=white)](web/vendor/LEAFLET-LICENSE.txt)
[![Rasterio](https://img.shields.io/badge/Rasterio-Geoprocessamento-236B52?style=flat-square)](src/pipeline.py)
[![scikit-learn](https://img.shields.io/badge/scikit--learn-Random_Forest-F7931E?style=flat-square&logo=scikitlearn&logoColor=white)](src/pipeline.py)
[![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-Automa%C3%A7%C3%A3o-2088FF?style=flat-square&logo=githubactions&logoColor=white)](.github/workflows/atualizar-mapas.yml)
[![Vercel](https://img.shields.io/badge/Vercel-Hospedagem-000000?style=flat-square&logo=vercel)](https://recife-calor.vercel.app/)

Observatório de temperatura da superfície e vegetação em Recife. O projeto combina imagens Landsat 8 e 9, análise por bairro e aprendizagem de máquina para explorar a distribuição do calor na cidade.

[Abrir o Recife Calor](https://recife-calor.vercel.app/) · [Como os dados são tratados](#como-os-dados-são-tratados) · [Estrutura do projeto](#estrutura-do-projeto) · [Executar localmente](#executar-localmente) · [Publicação na nuvem](#publicação-na-nuvem)

## O que o site oferece

| Recurso | O que é possível consultar |
| --- | --- |
| Mapa interativo | Temperatura superficial observada, vegetação (NDVI), contraste térmico e estimativa ajustada do modelo. |
| Consulta territorial | Busca por bairro, valores por célula de 120 m, médias por bairro e cobertura válida. |
| Histórico e comparação | Composições a partir de 2019, séries por bairro e comparação entre bairros ou anos. |
| Indicadores | Rankings de temperatura e vegetação, datas das cenas e avaliação do modelo. |
| Downloads | Estatísticas por bairro em CSV, camadas em GeoTIFF e métricas do modelo em JSON. |
| Recife, agora | Temperatura do ar e horário da observação do Aeroporto de Recife, estação SBRF. |

## Como os dados são tratados

1. O pipeline cruza a malha dos bairros fornecida pela Prefeitura de Recife com cenas Landsat 8/9 Collection 2 Level-2 do USGS, acessadas pelo catálogo STAC do Microsoft Planetary Computer.
2. A coleta seleciona até três cenas por ano, entre setembro e dezembro. As bandas de qualidade filtram nuvens, sombras, água, pixels saturados e observações com incerteza acima do limiar configurado.
3. As observações válidas são agregadas em células de 120 m. Quando há mais de uma cena válida para uma célula, a composição usa a mediana. O manifesto registra datas, cenas e cobertura.
4. O processamento calcula temperatura superficial, índices como NDVI, NDBI e NDWI, contraste térmico em relação à mediana municipal e estatísticas por bairro.

Cada composição representa as cenas selecionadas para o período. Compare os anos considerando as datas e a cobertura disponível. No painel, a maior temperatura observada corresponde à célula mais quente da composição. O cartão de temperatura do ar usa a medição pontual SBRF, com horário próprio.

## Modelo e avaliação

O Random Forest Regressor estima a temperatura superficial do Landsat a partir de índices espectrais e reflectâncias. A avaliação agrupa observações por blocos espaciais de 2,4 km e aplica uma faixa de 240 m entre pontos de treino e teste. MAE, RMSE e R² descrevem o desempenho fora do treino. A referência usa a média do conjunto de treinamento. A camada **Estimativa ajustada** usa o modelo treinado com todos os dados disponíveis.

## Estrutura do projeto

```text
recife-calor/
├── .github/workflows/
│   └── atualizar-mapas.yml       # Processa, valida e publica na nuvem
├── data/
│   └── processed/               # Dados preparados para consulta pelo site
├── outputs/
│   ├── maps/                    # Camadas PNG e GeoTIFF
│   ├── bairros_*.csv            # Indicadores por bairro e ano
│   ├── manifest.json            # Cenas, cobertura e parâmetros
│   └── metrics.json             # Avaliação do modelo
├── public/static/               # Recursos estáticos servidos na Vercel
├── src/
│   ├── common.py                # Configuração e funções compartilhadas
│   ├── pipeline.py              # Coleta, tratamento e treinamento
│   └── weather.py               # Consulta à estação meteorológica
├── web/                         # Interface, Leaflet, estilos e ilustrações
├── app.py                       # Aplicação Flask e API
├── main.py                      # Comando de processamento
├── config.json                  # Período, filtros e parâmetros de validação
├── preparar_publicacao.py       # Preparação do pacote de publicação
├── requirements.txt             # Dependências da aplicação
├── requirements-processing.txt  # Dependências de processamento
└── vercel.json                  # Configuração de hospedagem
```

## Executar localmente

No Windows, use o PowerShell com Git e Python 3.12.

```powershell
git clone https://github.com/nadjaguerra/recife-calor.git
cd recife-calor
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Abra o [endereço local](http://127.0.0.1:8000/). Para refazer a coleta e o treinamento, use as dependências de processamento. As fontes remotas exigem conexão à internet.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-processing.txt
.\.venv\Scripts\python.exe main.py
```

## Publicação na nuvem

O **GitHub Actions** coleta as imagens, recalcula os mapas e ajusta o modelo em um servidor hospedado pelo GitHub. A **Vercel** hospeda a aplicação Flask e serve os dados processados. O site e a rotina de atualização podem funcionar com o computador pessoal desligado.

O workflow está configurado para rodar às segundas-feiras, às 6h27 no horário de Recife, entre setembro e dezembro. Para iniciar manualmente, abra **Actions → Atualizar mapas do Recife Calor → Run workflow**. O workflow confere os anos disponíveis, testa rotas e compara o manifesto do deploy com o arquivo processado antes de promover a versão ao endereço público. Acompanhe pela [aba Actions](https://github.com/nadjaguerra/recife-calor/actions/workflows/atualizar-mapas.yml).

Em uma nova instalação, configure no GitHub o secret `VERCEL_TOKEN` e as variáveis `VERCEL_ORG_ID` e `VERCEL_PROJECT_ID`. As dependências de geoprocessamento e treinamento ficam em `requirements-processing.txt`.

## Fontes

- Imagens e produto de temperatura superficial. [USGS Landsat Collection 2](https://www.usgs.gov/landsat-missions/landsat-collection-2-surface-temperature) · [Catálogo Microsoft Planetary Computer](https://planetarycomputer.microsoft.com/dataset/landsat-c2-l2)
- Limites dos bairros. [Portal de Dados Abertos de Recife](https://dados.recife.pe.gov.br/dataset/area-urbana)
- Observação meteorológica SBRF. [Aviation Weather Center da NOAA](https://aviationweather.gov/data/api/)
- Mapas de fundo. [OpenStreetMap](https://www.openstreetmap.org/copyright) · [Esri World Imagery](https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer)
