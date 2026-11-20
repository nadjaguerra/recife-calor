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
| Análises espaciais | Diferença entre anos em células comuns, recorrência de áreas relativamente quentes, quantidade de cenas e erro de validação espacial. |
| Perfil de trajeto | Temperatura da superfície amostrada ao longo de uma linha definida no mapa. |
| Distribuições e sensibilidade | Quantis por bairro, faixas de NDVI, filtro de incerteza mais rigoroso e comparação com a primeira cena. |
| Contexto natural e populacional | Distâncias a parques, rios e ao Parque dos Manguezais, com população por bairro do Censo 2022. |
| Recife, agora | Temperatura do ar e horário da observação do Aeroporto de Recife, estação SBRF. |

## Como os dados são tratados

1. O pipeline cruza a malha dos bairros fornecida pela Prefeitura de Recife com cenas Landsat 8/9 Collection 2 Level-2 do USGS, acessadas pelo catálogo STAC do Microsoft Planetary Computer.
2. A coleta seleciona até três cenas por ano, entre setembro e dezembro. As bandas de qualidade filtram nuvens, sombras, água, pixels saturados e observações com incerteza acima do limiar configurado.
3. As observações válidas são agregadas em células de 120 m. Quando há mais de uma cena válida para uma célula, a composição usa a mediana. O manifesto registra datas, cenas e cobertura.
4. O processamento calcula temperatura superficial, índices como NDVI, NDBI e NDWI, contraste térmico em relação à mediana municipal e estatísticas por bairro.

Cada composição representa as cenas selecionadas para o período. Compare os anos considerando as datas e a cobertura disponível. No painel, a maior temperatura observada corresponde à célula mais quente da composição. O cartão de temperatura do ar usa a medição pontual SBRF, com horário próprio.

## Análises adicionais

A seção **Onde o calor se repete?** possui controles próprios de ano e referência. A frequência considera células pelo menos 2 °C acima da mediana municipal em cada composição e exige pelo menos três anos válidos. A diferença entre dois anos usa somente células válidas nos dois períodos. Os erros do modelo são previsões de validação fora do treinamento menos observações.

O teste térmico mais rigoroso utiliza um limite de incerteza de até 4 K, preservando os demais critérios e as mesmas cenas selecionadas. A comparação com a primeira cena permite explorar a sensibilidade à composição temporal. Os quantis e médias são calculados com todas as células válidas de cada grupo.

O contexto usa os cadastros municipais de parques, praças, recursos hídricos e unidades de conservação, consultados em 19/11/2026. A distância é aproximada na grade de 120 m, com áreas que tocam as células consideradas como distância zero. O recorte de manguezal corresponde à UCN Parque dos Manguezais. Os cadastros atuais são usados como referência de localização para todos os anos, sem afirmar que sua configuração era idêntica no passado.

O IBGE fornece a população de cada bairro em 2022, variável V0001 (Total de pessoas), do arquivo de agregados por bairro atualizado em 20/05/2026. A tabela contextual cruza a população do bairro com seus indicadores de superfície. Ela não estima a quantidade de pessoas nas células quentes. As fontes, datas e hashes estão em [data/contexto/fontes.json](data/contexto/fontes.json). A camada de rios está comprimida sem perda em GZIP.

## Modelo e avaliação

O Random Forest Regressor estima a temperatura superficial do Landsat a partir de índices espectrais e reflectâncias. A avaliação agrupa observações por blocos espaciais de 2,4 km e aplica uma faixa de 240 m entre pontos de treino e teste. MAE, RMSE e R² descrevem o desempenho fora do treino. A referência usa a média do conjunto de treinamento. A camada **Estimativa ajustada** usa o modelo treinado com todos os dados disponíveis.

## Estrutura do projeto

```text
recife-calor/
├── .github/workflows/
│   └── atualizar-mapas.yml       # Processa, valida e publica na nuvem
├── data/
│   ├── contexto/                # Bases municipais e população do Censo 2022
│   └── processed/               # Dados preparados para consulta pelo site
├── outputs/
│   ├── maps/                    # Camadas PNG e GeoTIFF
│   ├── bairros_*.csv            # Indicadores por bairro e ano
│   ├── manifest.json            # Cenas, cobertura e parâmetros
│   ├── research*.json            # Análises por ano e grade geográfica
│   └── metrics.json             # Avaliação do modelo
├── public/static/               # Recursos estáticos servidos na Vercel
├── src/
│   ├── common.py                # Configuração e funções compartilhadas
│   ├── pipeline.py              # Coleta, tratamento e treinamento
│   ├── research.py               # Análises espaciais e contexto
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
.\.venv\Scripts\python.exe -m pytest tests -q
```

## Publicação na nuvem

O **GitHub Actions** coleta as imagens, recalcula os mapas e ajusta o modelo em um servidor hospedado pelo GitHub. A **Vercel** hospeda a aplicação Flask e serve os dados processados. O site e a rotina de atualização podem funcionar com o computador pessoal desligado.

O workflow está configurado para rodar às segundas-feiras, às 6h27 no horário de Recife, entre setembro e dezembro. Para iniciar manualmente, abra **Actions → Atualizar mapas do Recife Calor → Run workflow**. O workflow confere os anos disponíveis e os testes científicos. A publicação usa a API oficial da Vercel. Depois do build, o endereço público é conferido contra o manifesto e as análises processadas; se essa conferência falhar, a rotina solicita a restauração da versão anterior. Acompanhe pela [aba Actions](https://github.com/nadjaguerra/recife-calor/actions/workflows/atualizar-mapas.yml).

Em uma nova instalação, configure no GitHub o secret `VERCEL_TOKEN` e as variáveis `VERCEL_ORG_ID` e `VERCEL_PROJECT_ID`. As dependências de geoprocessamento e treinamento ficam em `requirements-processing.txt`.

## Fontes

- Imagens e produto de temperatura superficial. [USGS Landsat Collection 2](https://www.usgs.gov/landsat-missions/landsat-collection-2-surface-temperature) · [Catálogo Microsoft Planetary Computer](https://planetarycomputer.microsoft.com/dataset/landsat-c2-l2)
- Limites dos bairros. [Portal de Dados Abertos de Recife](https://dados.recife.pe.gov.br/dataset/area-urbana)
- Observação meteorológica SBRF. [Aviation Weather Center da NOAA](https://aviationweather.gov/data/api/)
- Mapas de fundo. [OpenStreetMap](https://www.openstreetmap.org/copyright) · [Esri World Imagery](https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer)
