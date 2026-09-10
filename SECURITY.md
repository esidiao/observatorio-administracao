# Política de segurança e integridade dos dados

Este repositório não processa dados pessoais, não expõe serviço em execução e
não recebe entrada de usuário. A superfície de risco aqui é diferente da de uma
aplicação: o que pode dar errado é **um número errado ser publicado como se
fosse certo**.

## Reportar um problema

| Tipo | Como reportar |
|---|---|
| Divergência entre um número do site e a fonte primária | Abra uma issue com o indicador, a UF ou o município, o valor publicado e o valor da fonte |
| Vulnerabilidade no código do pipeline ou do gerador | Abra uma issue; se envolver credencial, escreva antes para sidiao@i9educar.com |
| Erro de interpretação ou de método | Abra uma issue descrevendo o raciocínio; método é discutível em público |

Divergência de dado tem prioridade sobre qualquer outra coisa neste projeto.

## Como a integridade é protegida

- **Portão GO.** As fórmulas dos índices e da estatística são conferidas contra
  valores calculados à mão antes de qualquer publicação.
- **Âncoras de regressão.** Os totais conhecidos do Censo e do CPC são testados
  a cada execução; mudança inesperada reprova o build.
- **Catálogo fechado.** Todo indicador publicado tem entrada de glossário e
  regra de formatação, geradas da mesma estrutura.
- **Guarda de riqueza.** O conjunto novo é comparado com o publicado; perda de
  campos aborta a publicação.
- **Proveniência.** Cada número carrega fonte, ano e data de extração, e o ano
  vem do arquivo lido, nunca do calendário.
- **Registro de anterioridade.** `data/registro_autoral.json` guarda o resumo
  SHA-256 de cada arquivo autoral.

## Dependências

O projeto usa `jinja2`, `openpyxl`, `pandas`, `pillow`, `py7zr` e `requests`, e
traz versionadas as bibliotecas de front-end (Leaflet, Chart.js) e as fontes.
Nenhum recurso é carregado de CDN em tempo de execução: o site funciona offline
e não expõe o leitor a terceiros.

`py7zr` existe por uma razão só: os microdados da RAIS são publicados em `.7z`,
formato que a biblioteca padrão do Python não lê. Ele é usado exclusivamente
para descompactar arquivos baixados do FTP oficial do Ministério do Trabalho, em
diretório temporário apagado ao fim de cada região.

O acesso às fontes é sempre por canal autenticado onde a fonte oferece um: o
contexto TLS usa o *truststore* do sistema — necessário porque o servidor do
INEP não envia o certificado intermediário e a cadeia só fecha por AIA. A
verificação de certificado **nunca** é desligada. Um observatório que se apoia
em proveniência não pode baixar dado oficial por canal não autenticado.

## O que este projeto não faz

Não coleta métricas de uso, não usa cookies, não carrega rastreadores e não
envia dado nenhum do leitor para lugar algum. O único armazenamento no
navegador é o cache do service worker, com os próprios arquivos do site.
