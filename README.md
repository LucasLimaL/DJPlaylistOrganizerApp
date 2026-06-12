# DJ Playlist Organizer

App local (roda no navegador) para DJs organizarem sua biblioteca de mp3s por
**gênero do Beatport** e manterem uma **playlist do Spotify** espelhando o que já
foi baixado. Multiplataforma (Windows, macOS, Linux) — só precisa de Python.

## Funcionalidades
- **Organizar por Beatport**: lê os mp3s da *pasta inicial*, descobre o gênero no
  Beatport, renomeia para `Artista - Título`, grava a tag de gênero e move/copia
  para `pasta final/<Gênero>/` (sem gênero → `Unknown`).
- **Copiar ou Mover** na organização (opção na interface).
- **Remover duplicatas** na pasta final (remove as certas, lista as ambíguas).
- **Sincronizar com o Spotify**: adiciona à playlist apenas as faixas que ainda não
  estão nela. Usa cache local para **não gastar API** com o que já é conhecido, e
  tem **limite** de faixas novas por execução (ótimo para testar).

## Requisitos
- Python 3.8+
- (Recomendado) `pip install --user mutagen` — leitura/escrita de tags.

## Como rodar
```bash
python app.py
```
Abre em `http://127.0.0.1:8765`.

## Configuração
- Crie um app grátis no [Spotify Developer Dashboard](https://developer.spotify.com/dashboard),
  cadastre o Redirect URI `http://127.0.0.1:8888/callback` e adicione sua conta em
  **User Management**.
- Preencha Client ID/Secret, pastas e nome da playlist pela própria interface
  (ou copie `config.example.json` para `config.json`).

## Segurança
O `config.json` (com seu Client Secret), tokens e caches **não são versionados**
(veja `.gitignore`). Nunca faça commit desses arquivos.

## Observações
- A descoberta de gênero no Beatport é *best-effort* (sem API pública de gênero):
  usa busca na web + a página da faixa. Pode errar ou cair em `Unknown`.
- A criação de playlist via API pode ser bloqueada em apps no modo desenvolvimento;
  nesse caso, crie a playlist manualmente no Spotify e o app só a abastece.
