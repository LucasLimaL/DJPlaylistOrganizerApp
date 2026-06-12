# Music Sync (app local)

Interface no navegador para (1) organizar mp3s por gênero do Beatport e
(2) sincronizar a coleção com uma playlist do Spotify. Roda em Windows, Mac e Linux.

## Instalar / rodar
1. Tenha o **Python 3.8+** (em Windows, marque "Add Python to PATH").
2. (Recomendado) instale o leitor de tags:  `pip install mutagen`
3. Rode dentro desta pasta:  `python app.py`
   - Abre sozinho em `http://127.0.0.1:8765`.

## Configurar
- **Pasta-raiz**: a pasta onde sua coleção fica organizada (ex.: `DJ - Final`). Use "Escolher…".
- **Client ID / Secret**: crie um app grátis em https://developer.spotify.com/dashboard
  e cadastre o Redirect URI **`http://127.0.0.1:8888/callback`**.
- **Nome da playlist**: padrão `Download Sync`.

## Usar
- **Organizar por Beatport**: coloque os mp3s NOVOS soltos na pasta-raiz e clique.
  O app descobre o gênero no Beatport e move cada um para `raiz/<Gênero>/`
  (renomeia para "Artista - Título" e grava o gênero na tag). Sem gênero → pasta `Unknown`.
- **Sincronizar com Spotify**: lê a pasta inteira, acha cada faixa no Spotify e adiciona
  na playlist (sem duplicar). Na 1ª vez abre o navegador para autorizar.

## Observações
- A busca de gênero no Beatport é **best-effort** (sem API pública de gênero): usa busca
  na web + a página da faixa. Funciona na maioria, mas pode errar ou cair em "Unknown".
  Confira e ajuste manualmente quando precisar.
- Se a conta/app do Spotify estiver em modo desenvolvimento e bloquear a CRIAÇÃO da
  playlist, crie uma playlist com o nome configurado no app do Spotify e rode o sync —
  ele só adiciona faixas (isso sempre funciona).
- Arquivos de cache/credenciais ficam nesta pasta (config.json, .spotify_token.json, etc).
