#!/usr/bin/env python3

import random
import re
import sqlite3
import string
import sys

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn import metrics
from sklearn.linear_model import LogisticRegression, SGDClassifier
from sklearn.naive_bayes import MultinomialNB
from sklearn.linear_model import Perceptron
from sklearn import svm
from sklearn.ensemble import RandomForestClassifier, AdaBoostClassifier
from sklearn.feature_selection import chi2, SelectKBest
from sklearn import cross_validation
from scipy import stats as ST
import matplotlib.pyplot as plt

REMOVE_PUNC = str.maketrans({key: None for key in string.punctuation})


def filter_study(title, condition, ec):
    """take one study and returns a filtered version with only relevant lines included"""
    lines = [title, condition]
    segments = re.split(
        r'\n+|(?:[A-Za-z0-9\(\)]{2,}\. +)|(?:[0-9]+\. +)|(?:[A-Z][A-Za-z]+ )+?[A-Z][A-Za-z]+: +|; +| (?=[A-Z][a-z])',
        ec, flags=re.MULTILINE)
    for i, l in enumerate(segments):
        l = l.strip()
        if l:
            l = l.translate(REMOVE_PUNC).strip()
            if l:
                lines.append(l)
    return '\n'.join(lines)


def vectorize_all(vectorizer, input_docs, fit=False):
    if fit:
        dtm = vectorizer.fit_transform(input_docs)
    else:
        dtm = vectorizer.transform(input_docs)
    return dtm


if __name__ == '__main__':
    conn = sqlite3.connect(sys.argv[1])
    c = conn.cursor()
    c.execute('SELECT t1.NCTId, t1.BriefTitle, t1.Condition, t1.EligibilityCriteria, t2.hiv_eligible FROM studies AS t1, hiv_status AS t2 WHERE t1.NCTId=t2.NCTId ORDER BY t1.NCTId')

    X = []
    y = []
    study_ids = []

    count = 0
    count_positive = 0
    for row in c.fetchall():
        text = filter_study(row[1], row[2], row[3])
        if text:
            X.append(text)
            y.append(row[4])
            study_ids.append(row[0])
            if row[4]:
                count_positive += 1
        else:
            print("[WARNING] no text returned from %s after filtering" % row[0])

    vectorizer = TfidfVectorizer(ngram_range=(1, 2))
    X = vectorize_all(vectorizer, X, fit=True)
    y = np.array(y)
    print(X.shape)

    chi2_best = SelectKBest(chi2, k=100)
    X = chi2_best.fit_transform(X, y)
    print(np.asarray(vectorizer.get_feature_names())[chi2_best.get_support()])

    stats = []
    seed = 0
    folds = 10
    print("CV folds: %s" % folds)

    label_map = ('HIV-ineligible', 'indeterminate', 'HIV-eligible')
    mean_fpr = {}
    mean_tpr = {}
    y_test_class = {}
    y_pred_class = {}
    for x in label_map:
        mean_fpr[x] = np.linspace(0, 1, 100)
        mean_tpr[x] = [0.0]
        y_test_class[x] = []
        y_pred_class[x] = []


    skf = cross_validation.StratifiedKFold(y, n_folds=folds, shuffle=True, random_state=seed)
    counter = 0
    for train, test in skf:
        X_train, X_test, y_train, y_test = X[train], X[test], y[train], y[test]

        # model = MultinomialNB()
        # model = LogisticRegression(class_weight={1: 5, 2: 12}, random_state=seed)
        # model = SGDClassifier(loss='hinge', n_iter=100, penalty='elasticnet')
        # model = svm.SVC(C=150, decision_function_shape='ovr',
        #                class_weight={1: 5, 2: 12}, random_state=seed)
        model = svm.LinearSVC(C=150, class_weight={1: 5, 2: 12}, random_state=seed)
        # model = RandomForestClassifier(class_weight='balanced')
        # model = AdaBoostClassifier(n_estimators=100)

        model.fit(X_train, y_train)
        y_predicted = model.predict(X_test)
        sd = list(metrics.precision_recall_fscore_support(y_test, y_predicted, beta=2, average=None))[:3]
        aucs = []
        ap_score = []
        for i, label in enumerate(label_map):
            bt = (y_test == i)
            bp = (y_predicted == i)
            y_test_class[label].extend(list(bt))
            y_pred_class[label].extend(list(bp))

            aucs.append(metrics.roc_auc_score(bt, bp))
            fpr, tpr, thresholds = metrics.roc_curve(bt, bp)
            mean_tpr[label] += np.interp(mean_fpr[label], fpr, tpr)
            mean_tpr[label][0] = 0.0

            ap_score.append(metrics.average_precision_score(bt, bp))

        sd.append(tuple(aucs))
        sd.append(tuple(ap_score))
        stats.append(sd)

        counter += 1

    for i, label in enumerate(label_map):
        stat_mean = {}
        for j, metric in enumerate(('precision', 'recall', 'F2 score', 'ROC-AUC score', 'PR-AUC score')):
            sd = [x[j][i] for x in stats]
            sd_mean = np.mean(sd)
            stat_mean[metric] = sd_mean
            sd_ci = ST.t.interval(0.95, len(sd) - 1, loc=sd_mean, scale=ST.sem(sd))
            print("%s %s: %s %s" % (label, metric, sd_mean, sd_ci))

        plt.figure(1)
        mean_tpr[label] /= folds
        mean_tpr[label][-1] = 1.0
        plt.plot(mean_fpr[label], mean_tpr[label],
                 label="%s (mean AUC = %0.2f)" % (label, stat_mean['ROC-AUC score']), lw=2)
        plt.figure(2)
        precision, recall, thresholds = metrics.precision_recall_curve(
            y_test_class[label], y_pred_class[label]
        )
        plt.plot(recall, precision,
                 label="%s (PR-AUC = %0.2f)" % (label, stat_mean['PR-AUC score']), lw=2)

    plt.figure(1)
    plt.xlim([0.0, 1.0])
    plt.ylim([0.0, 1.0])
    ax = plt.gca()
    limits = [
        np.min([ax.get_xlim(), ax.get_ylim()]),  # min of both axes
        np.max([ax.get_xlim(), ax.get_ylim()]),  # max of both axes
    ]
    plt.plot(limits, limits, 'k-', alpha=0.75, zorder=0)
    plt.xlabel('False Positive Rate')
    plt.ylabel('True Positive Rate')
    plt.title('Mean ROC')
    plt.legend(loc="lower right")

    plt.figure(2)
    plt.xlabel('Recall')
    plt.ylabel('Precision')
    plt.xlim([0.0, 1.0])
    plt.ylim([0.0, 1.0])
    plt.title('Precision-Recall')
    plt.legend(loc="lower left")

    plt.show()


        # print("Count     : %s" % len(true_scores))
    # print("CV folds  : %s" % cross_validation_count)
    # print("Accuracy  : %s" % accuracy_score(true_scores, predicted_scores))
    # # print("ROC-AUC   : %s" % roc_auc_score(true_scores, predicted_scores))
    # 
    
    # print("Confusion matrix:")
    # print(confusion_matrix(true_scores, predicted_scores))