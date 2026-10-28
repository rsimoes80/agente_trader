"""Research specialists: editorial scopes, not claims of completed book learning."""
from dataclasses import dataclass


@dataclass(frozen=True)
class BookProfile:
    id: str
    title: str
    documents: tuple[str, ...]
    scope: str
    stages: tuple[str, ...]
    kinds: tuple[str, ...]


PROFILES = (
    BookProfile('pullback', 'Manual do Pullback', ('EBOOK-MANUAL-DO-PULLBACK.pdf',),
                'Qualidade da correção, região, gatilho e invalidação; distinguir swing de M5.',
                ('context','region','trigger','invalidation','exit'), ('context','entry','invalidation','management','risk')),
    BookProfile('pring', 'Análise Técnica Explicada', ('analise-tecnica-explicadapdf-pdf-free.pdf',),
                'Horizontes de tendência, suporte e resistência e contexto dos rompimentos.',
                ('context','region','invalidation','exit'), ('context','entry','invalidation','management')),
    BookProfile('wyckoff', 'Wyckoff', ('wyckoff-20-portugues-pr.pdf',),
                'Estrutura, testes e resposta do preço; explicitar ausência de volume centralizado.',
                ('context','region','trigger','invalidation'), ('context','entry','invalidation')),
    BookProfile('brooks-trends', 'Brooks — Tendências', ('operando-price-action-tendencias-al-brooks-5-pdf-free.pdf',),
                'Continuação, canais e comportamento dos candles no contexto da tendência.',
                ('context','region','trigger','invalidation','exit'), ('context','entry','invalidation','management')),
    BookProfile('brooks-ranges', 'Brooks — Lateralidades', ('Operando Price Actions - Lateralidades (Al Brooks) (z-library.sk, 1lib.sk, z-lib.sk).pdf',),
                'Congestões, rompimentos e falhas; analisar lateralidade sem recomendar contra a tendência H1.',
                ('context','region','trigger','invalidation','exit'), ('context','entry','invalidation','management')),
    BookProfile('smc', 'Smart Money Concepts', ('Smart Money Concepts - MARRAIK SMC 2 (1).pdf',),
                'Estrutura e conceitos SMC explicitamente encontrados; não inferir intenção institucional de OHLC.',
                ('context','region','trigger','invalidation'), ('context','entry','invalidation')),
    BookProfile('douglas', 'Trading in the Zone', ('Trading_in_the_Zone.PDF','Trading_the_zone_traduzido_portugues.PDF'),
                'Disciplina, risco e avaliação por série; não criar gatilhos de preço. As traduções são a mesma obra.',
                ('risk','process'), ('risk','psychology','management')),
    BookProfile('livermore', 'Reminiscências de um Especulador Financeiro', ('Reminiscências de Um Especulador Financeiro por Jesse Livermore e Edward Lefèvre.pdf',),
                'Contexto e princípios operacionais; separar relatos históricos de regras testáveis.',
                ('context','risk','process'), ('context','risk','psychology')),
)
BY_ID = {p.id:p for p in PROFILES}
