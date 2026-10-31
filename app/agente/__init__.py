"""
O agente de IA: a parte que RECEBE a mensagem do cliente, conversa com o LLM e
usa as ferramentas de app/tools.

    provedor.py      único módulo que conhece a API de um fornecedor de LLM
    prompt.py        instruções fixas do agente (prompt de sistema)
    orquestrador.py  conduz um turno: modelo -> ferramenta -> modelo -> resposta
    historico.py     memória curta da conversa (só texto)
"""