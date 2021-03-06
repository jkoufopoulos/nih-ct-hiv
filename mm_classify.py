#!/usr/bin/env python3

import pickle
import sqlite3
import sys

import matplotlib.pyplot as plt
import numpy as np
from scipy import stats as ST
from sklearn import cross_validation
from sklearn import metrics
from sklearn import svm
from sklearn.feature_selection import chi2, SelectKBest

np.set_printoptions(precision=3)

DATABASE = 'studies.sqlite'


if __name__ == '__main__':
    conn = sqlite3.connect(DATABASE)
    c = conn.cursor()

    data = pickle.load(open(sys.argv[1], 'rb'))
    vectorizer = data['vectorizer']
    cui_names = data['cui_names']
    X = data['X']
    y = []
    study_ids = data['study_ids']
    for s in study_ids:
        c.execute('SELECT hiv_eligible FROM hiv_status WHERE NCTId=?', [s])
        y.append(c.fetchone()[0])
    y = np.array(y)

    print(X.shape)

    chi2_best = SelectKBest(chi2, k=500)
    X = chi2_best.fit_transform(X, y)
    print(X.shape)
    print([cui_names.get(x.upper(), x) for x in np.asarray(vectorizer.get_feature_names())[chi2_best.get_support()]])

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

    y_test_all = []
    y_pred_all = []

    skf = cross_validation.StratifiedKFold(y, n_folds=folds, shuffle=True, random_state=seed)
    counter = 0
    for train, test in skf:
        X_train, X_test, y_train, y_test = X[train], X[test], y[train], y[test]
        y_test_all.extend(y_test)

        model = svm.LinearSVC(C=8, class_weight={1: 5, 2: 12}, random_state=seed)

        model.fit(X_train, y_train)
        y_predicted = model.predict(X_test)
        y_pred_all.extend(y_predicted)
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

    print("Confusion matrix:")
    print(metrics.confusion_matrix(y_test_all, y_pred_all))

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
