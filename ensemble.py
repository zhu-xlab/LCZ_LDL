import numpy as np
import h5py
import os
import yaml
import json
from pathlib import Path
import pandas as pd

from utils.calibration import compute_calibration

from sklearn.metrics import accuracy_score
from sklearn.metrics import classification_report
from sklearn.metrics import cohen_kappa_score

import tensorflow as tf

## Set path ##
path = os.getcwd()

## Load test data ##

test_file = Path(path, "data", "test_data.h5")
test_data = h5py.File(test_file, 'r')
x_test = np.array(test_data.get("sen2"))
y_test = np.array(test_data.get("y"))

test_label_distributions = np.array(test_data.get("y_distributional_urban"))

## Subset to urban classes (1-10) ##

indices_test = np.where(np.where(y_test == np.amax(y_test, 0))[1] + 1 < 11)[0]
x_test = x_test[indices_test, :, :, :]
y_test = y_test[indices_test, :10]

## Save results to dataframe
results = pd.DataFrame()

## Model prediction ##

def evaluation(res_ckpt_filepath):

    ## Model settings
    from utils import model
    model = model.sen2LCZ_drop(depth=17,
                               dropRate=setting_dict["Data"]["dropout"],
                               fusion=setting_dict["Data"]["fusion"],
                               num_classes=setting_dict["Data"]["num_classes"])
    print("Model configured")

    model.load_weights(res_ckpt_filepath, by_name=False)
    # Store predictions + corresponding confidence
    y_pre_prob = model.predict(x_test, batch_size=setting_dict["Data"]["test_batch_size"])
    y_pre = y_pre_prob.argmax(axis=-1) + 1
    confidence = y_pre_prob[np.arange(y_pre_prob.shape[0]), (y_pre - 1).tolist()]

    return y_pre_prob, confidence


## Load settings dictionary ##

with open("configs/model_settings.yaml", 'r') as fp:
    setting_dict = yaml.load(fp, Loader=yaml.FullLoader)

## Train models ##

if __name__ == "__main__":
    for distributional in [False, True]:
        probs = np.array([])
        preds = np.array([])
        confs = np.array([])
        for seed in range(5):
            # Set hyperparameters accordingly
            setting_dict["Seed"] = seed
            setting_dict["Data"]["distributional"] = distributional
            batchSize = setting_dict["Data"]["train_batch_size"]
            lrate = setting_dict["Optimization"]["lr"]
            # Derive model checkpoint filename
            if distributional:
                res_ckpt_filepath = Path(path, "results",
                                     f"Sen2LCZ_bs_{batchSize}_lr_{lrate}_seed_{seed}_d_weights_best.hdf5")
            else:
                res_ckpt_filepath = Path(path, "results",
                                     f"Sen2LCZ_bs_{batchSize}_lr_{lrate}_seed_{seed}_weights_best.hdf5")
            prob, conf = evaluation(res_ckpt_filepath)

            # ToDo: Aggregate and average probs & confidences
            prob = prob[..., np.newaxis]
            conf = conf[..., np.newaxis]

            if seed == 0:
                probs = prob
                confs =conf
            else:
                probs = np.append(probs, prob, axis=2)
                confs = np.append(confs, conf, axis=1)

        y_pre_prob = np.average(probs, axis=2)
        confidence = np.average(confs, axis=1)

        y_pre = y_pre_prob.argmax(axis=-1) + 1
        y_testV = y_test.argmax(axis=-1) + 1

        # Compute performance metrics
        classRep = classification_report(y_testV, y_pre, digits=4, output_dict=True)
        oa = accuracy_score(y_testV, y_pre)
        macro_avg = classRep["macro avg"]["precision"]
        weighted_avg = classRep["weighted avg"]["precision"]
        cohKappa = cohen_kappa_score(y_testV, y_pre)
        # Derive cross-entropies and ece
        cce = tf.keras.losses.CategoricalCrossentropy()
        ce_distr = float(cce(test_label_distributions, y_pre_prob).cpu().numpy())
        ce_one_hot = float(cce(y_test, y_pre_prob).cpu().numpy())

        ece = \
        compute_calibration(y_testV, y_pre, confidence, y_pre_prob, num_bins=setting_dict["Calibration"]["n_bins"])[
            'expected_calibration_error']
        mce = \
        compute_calibration(y_testV, y_pre, confidence, y_pre_prob, num_bins=setting_dict["Calibration"]["n_bins"])[
            'max_calibration_error']
        sce = \
        compute_calibration(y_testV, y_pre, confidence, y_pre_prob, num_bins=setting_dict["Calibration"]["n_bins"])[
            'static_calibration_error']

        # Store results
        res = {
            'oa': float(oa),
            'maa': macro_avg,
            'waa': weighted_avg,
            'kappa': float(cohKappa),
            'ce_one_hot': ce_one_hot,
            'ce_distr': ce_distr,
            'ece': ece,
            'mce': mce,
            'sce': sce
        }

        # Store results in overall results matrix
        results = results.append(res, ignore_index=True)
# Write ALL results to disk
results.to_csv(Path(path,"results","0.002_results_ensemble.csv"))