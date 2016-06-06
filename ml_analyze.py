#!/usr/bin/env python3

import random
import re
import sqlite3
import string
import sys

import numpy as np
from scipy.sparse import coo_matrix, hstack
from sklearn.feature_extraction.text import CountVectorizer, HashingVectorizer
from sklearn.preprocessing import normalize
from sklearn.metrics import accuracy_score, classification_report, roc_auc_score, confusion_matrix
from sklearn.linear_model import LogisticRegression, SGDClassifier
from sklearn.naive_bayes import MultinomialNB
from sklearn.linear_model import Perceptron
from sklearn import svm
from sklearn.ensemble import RandomForestClassifier

from re_analyze import score_text as re_score_text


# signatures for line filtering
SIGNATURES = (
    (r'HIV', 0),
    (r'human immunodef', re.IGNORECASE),
    (r'immunodef', re.IGNORECASE),
    (r'immuno-?com', re.IGNORECASE),
    (r'(presence|uncontrolled|severe|chronic).+(disease|illness|condition)', re.IGNORECASE),
    (r'immune comp', re.IGNORECASE),
    (r'criteri', re.IGNORECASE),
    (r'characteristics', re.IGNORECASE),
    (r'inclusion|include', re.IGNORECASE),
    (r'exclusion|exclude', re.IGNORECASE)
)

REGEXES = [re.compile(x[0], flags=x[1]) for x in SIGNATURES]

REMOVE_PUNC = str.maketrans({key: None for key in string.punctuation})


def line_match(line):
    for rx in REGEXES:
        if rx.search(line):
            return True
    return False


def get_true_hiv_status(conn, id):
    c = conn.cursor()
    c.execute("SELECT hiv_eligible FROM hiv_status WHERE NCTId=?", [id])
    result = c.fetchone()
    if result is None:
        raise Exception("No annotation for %s" % id)
    else:
        return result[0]


def filter_study(study_text):
    """take one study and returns a filtered version with only relevant lines included"""
    lines = []
    pre = None
    segments = re.split(
        r'(\n+|(?:[A-Za-z0-9\(\)]{2,}\. +)|(?:[0-9]+\. +)|[A-Za-z]+ ?: +|; +|(?<!\()(?:[A-Z][a-z]+ ))',
        study_text, flags=re.MULTILINE)
    for i, l in enumerate(segments):
        m_pre = re.match(r'[A-Z][a-z]+ ', l)
        if m_pre:
            if i != len(segments) - 1:
                pre = l
                continue
            else:
                pre = None
        if l:
            if pre:
                l = pre + l
                pre = None
            l = l.translate(REMOVE_PUNC)
            if l:
                if line_match(l):
                    lines.append(l)
    return '\n'.join(lines)


def vectorize_all(vectorizer, input_docs, fit=False):
    if fit:
        dtm = vectorizer.fit_transform(input_docs)
    else:
        dtm = vectorizer.transform(input_docs)
    return dtm


if __name__ == '__main__':
    for x in REGEXES:
        print(x)

    conn = sqlite3.connect(sys.argv[1])
    c = conn.cursor()
    c.execute('SELECT t1.NCTId, t1.BriefTitle, t1.Condition, t1.EligibilityCriteria, t2.hiv_eligible FROM studies AS t1, hiv_status AS t2 WHERE t1.NCTId=t2.NCTId ORDER BY t1.NCTId')

    X_training = []
    y_training = []
    X_test = []
    X_test_raw = []
    y_true = []
    test_line_map = []   # line ranges for each study

    train_count = 0
    train_positive = 0
    test_positive = 0
    test_labels = []
    for row in c.fetchall():
        text = filter_study('\n'.join(row[1:4]))
        if text:
            if random.random() >= 0.4:
                X_training.append(text)
                y_training.append(row[4])
                train_count += 1
                if row[4]:
                    train_positive += 1
            else:
                X_test_raw.append(row[3])
                X_test.append(text)
                y_true.append(row[4])
                if row[4]:
                    test_positive += 1
                test_labels.append(row[0])
        else:
            print("[WARNING] no text returned from %s after filtering" % row[0])

    vectorizer = CountVectorizer(ngram_range=(1, 2))
    X_training = vectorize_all(vectorizer, X_training, fit=True)
    X_test = vectorize_all(vectorizer, X_test)

    #model = MultinomialNB()
    model = LogisticRegression(class_weight='balanced')
    #model = SGDClassifier(loss='log', n_iter=100)
    #model = svm.SVC(class_weight='balanced')
    #model = RandomForestClassifier(class_weight='balanced')
    model.fit(X_training, y_training)

    y_test = model.predict(X_test)

    true_scores = y_true
    predicted_scores = y_test
    assert(len(true_scores) == len(predicted_scores) == len(test_labels))

    mismatches_fp = []
    mismatches_fn = []
    for i in range(len(true_scores)):
        if true_scores[i] != predicted_scores[i]:
            if predicted_scores[i] == 0:
                mismatches_fn.append(test_labels[i])
            else:
                mismatches_fp.append(test_labels[i])
    print("FP        : %s" % str(mismatches_fp))
    print("FN        : %s" % str(mismatches_fn))
    print("Trn count : %s" % train_count)
    print("Training +: %s" % train_positive)
    print("Test count: %s" % len(true_scores))
    print("Test +    : %s" % test_positive)
    print("Accuracy  : %s" % accuracy_score(true_scores, predicted_scores))
    print(classification_report(true_scores, predicted_scores, target_names=['HIV-ineligible', 'HIV-eligible']))
    print("AUC:      : %s" % roc_auc_score(true_scores, predicted_scores))
    print("Confusion matrix:")
    print(confusion_matrix(true_scores, predicted_scores))
