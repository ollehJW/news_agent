"""Topic-independent 40:30:30 scoring on a 100-point scale."""

SCORE_VERSION='v1'
BASE_SCORES=('technical_score','organization_score','impact_score')

def weighted_scores(article):
    if any(article.get(k) is None for k in BASE_SCORES):
        return {'total_score':None}
    total=int((article['technical_score']*40+article['organization_score']*30+article['impact_score']*30+50)//100)
    return {'total_score':total}


def evaluation_complete(article):
    return (article.get('score_version')==SCORE_VERSION and bool((article.get('summary') or '').strip())
            and bool((article.get('newsletter_title') or '').strip())
            and all(isinstance(article.get(k),(int,float)) and 0<=article[k]<=100 for k in BASE_SCORES))
