"""Significado, finalidade e evidências editoriais do catálogo analítico."""

from .transformacoes_silver import AREAS


VERSAO_GOLD = "2.0.0"
VERSAO_POLITICA = "2.0.0"

INDICADORES = {
    "vigitel_atividade_fisica_lazer": (
        "CORPO_E_SAUDE",
        "Atividade física suficiente no lazer",
        "Como a atividade física aparece na população de referência?",
        "Contextualizar a área sem avaliar suficiência pessoal por missões.",
    ),
    "vigitel_sintomas_insonia": (
        "SONO_E_RECUPERACAO",
        "Sintomas frequentes de insônia",
        "Como as pessoas relatam dificuldades de sono?",
        "Reconhecer uma dimensão do sono que a duração isolada não descreve; sem diagnóstico.",
    ),
    "vigitel_duracao_sono_habitual": (
        "SONO_E_RECUPERACAO",
        "Sono habitual por noite",
        "Como varia o sono habitual declarado?",
        "Contextualizar diversidade, sem estabelecer uma meta pessoal.",
    ),
    "vigitel_duracao_sono_desejada": (
        "SONO_E_RECUPERACAO",
        "Sono desejado para sentir-se recuperado",
        "Quanto as pessoas gostariam de dormir?",
        "Explicitar preferência declarada, sem interpretar como necessidade clínica.",
    ),
    "vigitel_deseja_mais_sono": (
        "SONO_E_RECUPERACAO",
        "Desejo de dormir mais que o habitual",
        "Há diferença entre sono habitual e desejado?",
        "Apoiar reflexão sobre recuperação, sem atribuir déficit ao usuário.",
    ),
    "atus_sono_diario": (
        AREAS["atus_sono_diario"],
        "Sono registrado no diário, incluindo cochilos",
        "Como o sono aparece no diário de 24 horas?",
        "Distinguir sono diário ATUS de sono noturno habitual Vigitel.",
    ),
    "atus_aulas_tarefas_estudo": (
        AREAS["atus_aulas_tarefas_estudo"],
        "Aulas e tarefas de estudo",
        "Como aparecem aulas e tarefas na rotina?",
        "Referência detalhada; não sugerir duração de sessão individual.",
    ),
    "atus_aulas": (
        AREAS["atus_aulas"],
        "Participação em aulas",
        "Que parte do estudo corresponde a aulas?",
        "Distinguir compromissos de aula das tarefas de estudo.",
    ),
    "atus_tarefas_estudo": (
        AREAS["atus_tarefas_estudo"],
        "Tarefas e pesquisa para aulas",
        "Como aparecem tarefas de estudo fora das aulas?",
        "Separar tarefas de aulas ao refletir sobre o planejamento; não mede eficácia.",
    ),
    "atus_trabalho_empregos": (
        AREAS["atus_trabalho_empregos"],
        "Trabalho nos empregos",
        "Como o trabalho aparece na rotina de referência?",
        "Contextualizar compromissos; horas trabalhadas não medem produtividade.",
    ),
    "atus_lazer_selecionado": (
        AREAS["atus_lazer_selecionado"],
        "Atividades selecionadas de lazer",
        "Como o lazer aparece na rotina?",
        "Contextualizar lazer sem tratar seu tempo como disponibilidade para novas metas.",
    ),
    "atus_casa_alimentacao": (
        AREAS["atus_casa_alimentacao"],
        "Tarefas domésticas e preparo de alimentos",
        "Quais demandas domésticas também entram na rotina?",
        "Reconhecer demandas além de trabalho e estudo; não mede todo cuidado ou trabalho doméstico.",
    ),
    "atus_deslocamento_trabalho": (
        AREAS["atus_deslocamento_trabalho"],
        "Deslocamentos relacionados ao trabalho",
        "Como os deslocamentos de trabalho aparecem na rotina?",
        "Lembrar o contexto de deslocamento ao planejar; não atribuir tempo ao usuário.",
    ),
    "atus_deslocamento_aulas": (
        AREAS["atus_deslocamento_aulas"],
        "Deslocamentos relacionados a aulas",
        "Como os deslocamentos de aulas aparecem na rotina?",
        "Reconhecer compromissos de deslocamento; não supor janela de estudo durante o trajeto.",
    ),
    "vigitel_atividade_sintomas_sono": (
        "SONO_E_RECUPERACAO",
        "Atividade física e sintomas de sono",
        "Como atividade física e sintomas de sono aparecem nas mesmas entrevistas?",
        "Explicar uma associação populacional, sem atribuir efeito de treino ou chance de sucesso.",
    ),
    "vigitel_atividade_deseja_mais_sono": (
        "SONO_E_RECUPERACAO",
        "Atividade física e desejo de dormir mais",
        "Como atividade física se relaciona ao sono desejado declarado?",
        "Contextualizar coexistência de comportamentos, sem previsão ou prescrição.",
    ),
}

# Curadoria de fontes primárias: sínteses próprias, sem microdados ou texto integral.
EVIDENCIAS = [
    {
        "id": "sono_restricao_desempenho_2003",
        "tipo": "evidencia_pesquisa",
        "area_da_vida": "SONO_E_RECUPERACAO",
        "ano": 2003,
        "doi": "10.1093/sleep/26.2.117",
        "url": "https://academic.oup.com/sleep/article/26/2/117/2709164",
        "titulo": "Restrição de sono e desempenho cognitivo em laboratório",
        "populacao": "48 adultos saudáveis de 21–38 anos; laboratório nos EUA",
        "desenho": "Experimentos de restrição de sono com alocação aleatória entre doses; comparação com privação total.",
        "intervencao": "Janelas de 4, 6 ou 8 horas na cama durante 14 noites; outro experimento com privação total.",
        "desfecho": "Desempenho em tarefas cognitivas e vigilância, não conquistas de vida.",
        "achado": "As condições de restrição a 4 ou 6 horas produziram prejuízos cognitivos cumulativos nas tarefas avaliadas.",
        "reflexao": "Compreender por que o sono é relevante ao discutir condições para tarefas que exigem atenção.",
        "limites": "Experimento em laboratório; não calcula benefício individual de dormir mais ou chance de concluir uma meta; tempo na cama não equivale a sono medido.",
        "usos_permitidos": ["contexto_educativo"],
    },
    {
        "id": "sono_extensao_trabalho_2021",
        "tipo": "evidencia_pesquisa",
        "area_da_vida": "SONO_E_RECUPERACAO",
        "ano": 2021,
        "doi": "10.1093/qje/qjab013",
        "url": "https://economics.mit.edu/sites/default/files/2022-09/economic-sleep-qje.pdf",
        "titulo": "Extensão do sono e resultados de trabalho em campo",
        "populacao": "452 adultos de baixa renda em Chennai, Índia; trabalho de digitação",
        "desenho": "Ensaio aleatório de campo com intervenções noturnas e oportunidade de cochilo.",
        "intervencao": "Informação, incentivo e melhorias do ambiente durante três semanas aumentaram o sono noturno em média em 27 minutos.",
        "desfecho": "Produtividade em digitação, cognição e outros resultados no contexto estudado.",
        "achado": "O aumento do sono noturno não produziu ganho detectável de produtividade; a intervenção de cochilos teve resultados diferentes.",
        "reflexao": "Explicar que os resultados dependem do contexto, da intervenção e do desfecho avaliado.",
        "limites": "Não conclui que sono é irrelevante; não generalizar para todo trabalho, idade ou condição, nem recomendar cochilos com base apenas nesse resumo.",
        "usos_permitidos": ["contexto_educativo"],
    },
]
