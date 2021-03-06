import sys
import numpy as np
import pandas as pd
import MySQLdb as mdb
import sklearn.feature_extraction
import sklearn.linear_model
import sklearn.grid_search
import time
import cPickle as pickle

import flightfuncs as ff
import load_credentials_nogit as creds

def train_log(tablename,continuous_predictors = [],discrete_predictors = ['origin','dest','uniquecarrier','dayofweek(flightdate)'],targetname = 'arrdelay',subset=None,timesplit = [15,45],filename = None, C_vals = [0.1,10,1000,100000]):
    '''
    Train and fit a logarithmic regression classifier.

    Arguments:
    tablename -- the name of the database table to query.
    continuous_predictors -- a list of names of continuous predictors to use (default = []).
    discrete_predictors -- a list of names of discrete predictors to use (default = ['origin','dest','uniquecarrier','dayofweek(flightdate)']).
    targetname -- the name of the column that will be the target (default = arrdelay).
    subset -- take a subset of the data (default = None).
    timesplit -- a list of the bin edges the target labels will be split into (default = [15,45]).
    filename -- save the model to a file, and if so what should its name be? (default = None).
    C_vals -- values of the C parameter to test for when cross-validating (default =  [0.1,10,1000,100000]).

    Returns:
    If filename != None, prints out a pickle file containing the trained model as well as useful supplementary information, such as how the target and features were coded.
    '''
    start = time.time()
    #Connect to the database and download the data:
    con = mdb.connect(host=creds.host,user=creds.user,db=creds.database,passwd=creds.password,local_infile=1)
    data = ff.query_into_pd(con,tablename,continuous_predictors+discrete_predictors+[targetname] + ['cancelled','diverted'],subset=subset,randomize=True)
    print "Finished querying data ({0:.2f}s)".format(time.time()-start)
    
    #Select only flights that weren't diverted:
    diverted_bool = (data.diverted > 1.e-5)
    data = data[(diverted_bool == False)]

    #Code up the delay times:
    tc = ff.TimeCoder(timesplit)
    coded_delays = tc.time_encode(data[targetname].values,data.cancelled.values)
    print "Finished coding the target ({0:.2f}s)".format(time.time()-start)

    #Code up the predictors. All of the ones I'm currently dealing with are categorical and strings, so I tried a DictVectorizer to save space, but it was super slow and didn't really seem to be saving that many GB. So I wrote my own (non-sparse) encoder that's designed to deal in an efficient manner with how I'm piping in my data.
    coder = ff.PredictorCoder()
    pred_code = coder.train(data,continuous_predictors,discrete_predictors)
    print "Finished coding the predictors ({0:.2f}s)".format(time.time()-start)

    #Free up memory by chucking the data
    del data

    #Train the logistic regression model:
    logreg = sklearn.grid_search.GridSearchCV(sklearn.linear_model.LogisticRegression(),param_grid={'C':C_vals},scoring=ff.pdf_scoring,cv=2)
    logreg.fit(pred_code,coded_delays)
    print "Best C = {C}".format(**logreg.best_params_)
    print "Finished training the model ({0:.2f}s)".format(time.time()-start)

    #Output a pickled file containing the model and the necessary supporting information:
    if filename != None:
        pklfile = open(filename,'wb')
        regression_dict = {'model':logreg,'target_coder':tc,'predictor_coder':coder,'table_name':tablename,'subset':subset}
        pickle.dump(regression_dict,pklfile)
        pklfile.close()

def test_run(model_file):
    '''
    A simple test case.
    '''
    f = open(model_file,'rb')
    model_dict = pickle.load(f)
    f.close()
    sampledict = {'origin': pd.Series(['MSN','DEN','LAX']),
                  'dest': pd.Series(['ORD','JFK','ORD']),
                  'uniquecarrier': pd.Series(['UA','UA','UA']),
                  'dayofweek(flightdate)' : pd.Series([2,2,2]),
                  'label': pd.Series(['United - MSN->ORD','United - DEN->JFK','United - LAX->ORD'])
                  }
    sampledf = pd.DataFrame(sampledict)
    sample_code = model_dict['predictor_coder'].code_data(sampledf)
    sample_probabilities = model_dict['model'].predict_proba(sample_code)
    timecodes = [model_dict['target_coder'].bin_text_dict[key] for key in range(sample_probabilities.shape[1])]
    output_df = pd.DataFrame(sample_probabilities,columns=timecodes)
    print output_df
    
    
if __name__ == "__main__":
    #np.random.seed(1)
    if len(sys.argv) != 3:
        sys.exit("Syntax: [Shard name] [subset (integer or 'none')]")
    tablename = sys.argv[1]
    subset = None
    try:
        subset = int(sys.argv[2])
    except ValueError:
        subset = None
    filename = '../saved_models/test_logreg.pkl'
    train_log(tablename,discrete_predictors = ['origin','dest','uniquecarrier'],subset=subset,filename=filename)
    test_run(filename)
