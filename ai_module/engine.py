# PyLab AI - AI Engine Module

def ai_answer_question(question, topic=''):
    q = question.lower().strip()
    # Detect topic from question
    if not topic:
        for t in ['loop','for','while','function','list','dict','string','class','oop','decorator','generator','exception','file','module','lambda','recursion','variable','operator','condition','if']:
            if t in q:
                topic = t
                break
    return generate_topic_explanation(topic, question)
