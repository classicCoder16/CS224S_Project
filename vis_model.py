'''
This file loads a pre-trained model from the "models/" directory.
It then tests the model on the test data.
'''
import os
import sys
import math
from time import gmtime, strftime
import time
import numpy as np
import tensorflow as tf
import argparse
from data_loader import DataLoader
import editdistance
from sklearn.manifold import TSNE
import matplotlib
matplotlib.use('agg')
import matplotlib.pyplot as plt
model = None
DL = None
results_dir = None

def parse_arguments():
	parser = argparse.ArgumentParser(description='Tests a pre-trained end-to-end neural ASR model')
	parser.add_argument('-m', '--model', default='baseline', help="Model you would like to evaluate")
	parser.add_argument('-e', '--expdir', default=None, help="Name of experiment you would like to evaluate")
	parser.add_argument('-rf', '--restorefile', default=None, help="What filename you would like to load the model from, default is None.")
	parser.add_argument('-d', '--data', default='wsj', help="What dataset you would like to use")
	parser.add_argument('-s', '--split', default='test', help='What split of the data you want to test on')
	parser.add_argument('-c', '--count', default=None, help='How many examples do you want to evaluate')
	parser.add_argument('-n', '--normalize', default=False, type=bool, help='Whether you want to normalize features')
	parser.add_argument('-g', '--gpu', default=None, type=int, help='Whether you want to run on a specific GPU')
	parser.add_argument('-nl', '--num_layers', default=2, type=int, help='How many layers the original model had')
	parser.add_argument('-l', '--loop', default=None, help='Whether the greedy decoder uses a loop function')  
	parser.add_argument('-emb', '--embedding_size', default=None, type=int, help="How large the embedding dimension should be")
	parser.add_argument('-bs', '--beam_search', default=None, help="Whether you would like to decode with beam search")
	parser.add_argument('-nb', '--num_beams', default=12, help="Whether you would like to decode with beam search")
	parser.add_argument('-bt', '--beam_threshold', default=0.0, type=float, help="What threshold to use during beamsearch")
	parser.add_argument('-nc', '--num_cells', default=64, type=int, help="How many cells to use for the memory-based models.")
	args = parser.parse_args()
	return args


def load_model_and_data(args):
	print args
	# Get model name
	model_name = args.model
	full_path = os.path.dirname(os.path.abspath(__file__))+'/models/' + model_name
	sys.path.insert(0, full_path)

	# Import the config and model from their respective files
	global config
	import config
	config.num_layers = args.num_layers
	config.loop = args.loop
	config.beam_search = args.beam_search
	config.num_beams = int(args.num_beams)
	config.beam_threshold = float(args.beam_threshold)
	config.num_cells = int(args.num_cells)
	if args.data == 'wsj':
		config.max_in_len = 500
		config.max_out_len = 200
		config.vocab_size = 27
	elif args.data == 'chime2_grid':
		config.max_in_len = 100
		config.max_out_len = 30
		config.vocab_size = 27
	elif args.data == 'tidigits':
		config.max_in_len = 170
		config.max_out_len = 7
		config.vocab_size = 11
	config.vocab_size += 3
	if args.embedding_size is not None:
		config.embedding_dim = args.embedding_size
	print 'Current config:\n'
    	variables = zip(vars(config).keys(), vars(config).values())
    	for var, val in sorted(variables):
        	print var + ' = ' + str(val)

	print 'Creating graph...'
	from model import ASRModel
	global model
	model = ASRModel(config)

	print 'Loading training data'
	DL_train = DataLoader(args.data, config=config, normalize=args.normalize, split='train')

	print 'Loading data'
	global DL

	# Since we've already loaded the training data for mean normalization
	if args.split == 'train':
		DL = DL_train
	else:
		DL = DataLoader(args.data, config=config, normalize=args.normalize, mean_vector=DL_train.mean_vector, split=args.split)

	global results_dir
	results_dir ='results/' + args.model + '/' + args.expdir

'''
Helper function that returns list of predictions
'''
def get_mems(sess, data, num, DL):
	test_data = [elem[:num] for elem in data]
	i = 0
	all_mems = []
	all_labels = []
	while i < num:
		print 'i = ', i

		# Batch indices to grab
		min_i = i
		max_i = i + config.batch_size

		# Get the batch data
		input_features, seq_lens, labels, masks = tuple([elem[min_i:max_i] for elem in test_data])
		
		# Batch size, num cells, memory len
		init_memory = model.get_memory(sess, input_features, seq_lens, labels)
		#avg_mems = np.mean(init_memory, axis=1)
		avg_mems = init_memory[:, 0, :]
		all_mems += list(avg_mems)
		for label in labels:
			all_labels.append(DL.decode(label))
		# Shift i
		i += config.batch_size

	# Return result
	return np.array(all_mems), all_labels


def visualize(args):
	# Init function for all variables
	init = tf.global_variables_initializer()

	# Allow soft placement on other GPUs
	config2 = tf.ConfigProto(allow_soft_placement = True)

	# Create a session
	with tf.Session(config=config2) as sess:

		# Run initialization
		sess.run(init)

		# Saves the model to a file, or restores it
		saver = tf.train.Saver(tf.trainable_variables())

		if args.restorefile:
			print 'Restoring from ' + args.restorefile
			saver.restore(sess, results_dir + '/' + args.restorefile)
		else:
			print 'No file given, restoring most recent'
			ckpt = tf.train.get_checkpoint_state(results_dir)
			if ckpt and ckpt.model_checkpoint_path:
				print 'Restoring from ' + ckpt.model_checkpoint_path
				saver.restore(sess, ckpt.model_checkpoint_path)

		test_data = DL.data
		num_to_evaluate = DL.num_examples

		# Use the count passed in if there is one
		if args.count is not None:
			num_to_evaluate = args.count
		print 'Visualizing ' + str(num_to_evaluate) + ' examples' 

		# Get the predictions and labels in a batch fashion
		all_average_memories, labels = get_mems(sess, test_data, int(num_to_evaluate), DL)
		print all_average_memories
		tsne_model = TSNE(n_components=2, random_state=0)
		print 'Fitting data'
		fit_data = tsne_model.fit_transform(all_average_memories)
		data_x = fit_data[:, 0]
		data_y = fit_data[:, 1]
		plt.figure()
        for x,y,char in zip(data_x, data_y,labels):
            plt.scatter(x,y, c='r')
            plt.annotate(char[3], xy=(x,y))
        plt.savefig('Plot')
	plt.close()


		



if __name__=='__main__':
	args = parse_arguments()
	print 'Testing on ' + args.split + ' split'
	load_model_and_data(args)	
	visualize(args)
