'''
Model definition for baseline seq-to-seq model.
'''
import tensorflow as tf
from tf_beam_decoder import beam_decoder
import numpy as np
import self.config
from my_att_cell import MyAttCell

class ASRModel:

	def __init__(self, config):
		self.config = config
		self.build_graph()

	def build_graph(self):

		# Create placeholders
		self.add_placeholders()

		# Add embedding
		self.add_embedding()

		# Define encoder structure
		self.add_encoder()

		# Store the custom cell
		self.cell = MyAttCell(memory=self.memory, num_units = self.config.decoder_hidden_size)

		# Define decoder structure
		self.add_decoder()

		# Branch of graph to take if we're just doing
		# prediction
		self.add_decoder_test()

		self.add_loss_op()

		self.add_training_op()

		self.add_summary_op()


	def add_placeholders(self):
		print 'Adding placeholders'
		self.input_placeholder = tf.placeholder(tf.float32, shape=(None, None, self.config.num_input_features), name='inputs')
		self.labels_placeholder = tf.placeholder(tf.int32, shape=(None, self.config.max_out_len + 2), name="target_seq")
		self.input_seq_lens = tf.placeholder(tf.int32, shape=(None), name='in_seq_lens')
		self.mask_placeholder = tf.placeholder(tf.float32, shape=(None, self.config.max_out_len + 2), name="mask")


	def add_embedding(self):
		self.L = tf.get_variable("L", dtype=tf.float32, shape=(self.config.vocab_size, self.config.embedding_dim))

	def create_feed_dict(self, inputs, seq_lens=None, labels=None, mask=None, dropout=None):
		'''
		Creates and returns a feed dictionary since training file 
		can't easily access the model Tensors.
		'''
		feed_dict = {}

		# We always need some type of input
		feed_dict[self.input_placeholder] = inputs

		if seq_lens is not None:
			feed_dict[self.input_seq_lens] = seq_lens

		# The labels may not always be provided
		if labels is not None:
			feed_dict[self.labels_placeholder] = labels

		if mask is not None:
			feed_dict[self.mask_placeholder] = mask

		# Dropout may not actually be provided
		if dropout is not None:
			feed_dict[self.dropout_placeholder] = dropout

		return feed_dict

	def add_encoder(self):
		print 'Adding encoder'
		# Use a GRU to encode the inputs
		with tf.variable_scope('Encoder'):
			cell_fw = tf.nn.rnn_cell.GRUCell(num_units = self.config.encoder_hidden_size)
			cell_bw = tf.nn.rnn_cell.GRUCell(num_units = self.config.encoder_hidden_size)
			outputs, states = tf.nn.bidirectional_dynamic_rnn(cell_fw = cell_fw, cell_bw = cell_bw, inputs=self.input_placeholder, \
											sequence_length=self.input_seq_lens, dtype=tf.float32)
			h1_vals = tf.concat(2, outputs)
			filter_1 = tf.get_variable('filters1', shape=(4, h1_vals.get_shape().as_list()[-1], 100), \
									initializer=tf.contrib.layers.xavier_initializer())
			conv1 = tf.nn.relu(tf.nn.conv1d(value = h1_vals, filters = filter_1, \
											stride = 2, padding = 'SAME', name = 'conv1'))

			filter_2 = tf.get_variable('filters2', shape=(4, 100, 50), \
									initializer=tf.contrib.layers.xavier_initializer())

			conv2 = tf.nn.relu(tf.nn.conv1d(value = conv1, filters = filter_2, \
											stride = 2, padding = 'SAME', name = 'conv2'))

			cell2 = tf.nn.rnn_cell.GRUCell(num_units = self.config.encoder_hidden_size)
			final_outputs, final_state = tf.nn.dynamic_rnn(cell=cell2, inputs=conv2, dtype=tf.float32)
			self.encoded = final_state
			self.memory = final_outputs
			print 'Memory shape', self.memory.get_shape()
			print 'Encoded shape', self.encoded.get_shape()
			# self.memory = tf.concat(2, outputs)
			# print 'Memory shape', self.memory.get_shape()


	def add_decoder(self):
		print 'Adding decoder'
		scope='Decoder'
		with tf.variable_scope(scope):
			# Reshape
			decoder_inputs = tf.nn.embedding_lookup(self.L, ids=self.labels_placeholder)
			decoder_inputs = tf.unstack(decoder_inputs, axis=1)[:-1]
			outputs, _ = tf.nn.seq2seq.rnn_decoder(decoder_inputs=decoder_inputs,\
												initial_state = self.encoded,\
												cell=self.cell, loop_function=None, scope=scope)
			# Get variable
			W = tf.get_variable('W', shape=(self.config.decoder_hidden_size, self.config.vocab_size), \
								initializer=tf.contrib.layers.xavier_initializer())
			b = tf.get_variable('b', shape=(self.config.vocab_size,), \
								initializer=tf.constant_initializer(0.0))

			# Convert outputs back into Tensor
			tensor_preds = tf.stack(outputs, axis=1)

			# Compute dot product
			original_shape = tf.shape(tensor_preds)
			outputs_flat = tf.reshape(tensor_preds, [-1, self.config.decoder_hidden_size])
			logits_flat = tf.matmul(outputs_flat, W) + b

			# Reshape back into 3D
			self.logits = tf.reshape(logits_flat, [original_shape[0], original_shape[1], self.config.vocab_size])
			print 'Logits shape', self.logits.get_shape()


	'''
	Identitical to add_decoder, but geared towards decoding at test time by
	feeding in the previously generated element.
	'''
	def add_decoder_test(self):
		print 'Adding decoder test'
		scope='Decoder'
		with tf.variable_scope(scope, reuse=True):

			W = tf.get_variable('W')
			b = tf.get_variable('b')

			def output_fn(inputs):
				original_shape = tf.shape(inputs)
				outputs_flat = tf.reshape(inputs, [-1, self.config.decoder_hidden_size])
				logits_flat = tf.matmul(outputs_flat, W) + b
				logits = tf.reshape(logits_flat, [original_shape[0], original_shape[1], self.config.vocab_size])
				return tf.nn.log_softmax(logits)

			def emb_fn(tokens):
				original_shape = tf.shape(tokens)
				outputs = tf.nn.embedding_lookup(self.L, tokens)
				return tf.reshape(outputs, [original_shape[0], original_shape[1], self.config.embedding_dim])

			start_tokens = tf.nn.embedding_lookup(self.L, self.labels_placeholder[:, 0])
			self.decoded, _ = beam_decoder(
			    cell=self.cell,
			    beam_size=self.config.num_beams,
			    stop_token=29,
			    initial_state=self.encoded,
			    initial_input=start_tokens,
			    tokens_to_inputs_fn=emb_fn,
			    max_len=self.config.max_out_len,
			    scope=scope,
			    outputs_to_score_fn=output_fn,
			    output_dense=True,
			    cell_transform='replicate',
			    score_upper_bound=0.0
			)

	'''
	function: add_loss_op
	-------------------------
	Given the logits produced by the decoder, computes average loss over non-padded
	timesteps
	'''
	def add_loss_op(self):
		print 'Adding loss'
		# Compute sparse cross entropy againnst the logits
		all_losses = tf.nn.sparse_softmax_cross_entropy_with_logits(logits=self.logits, labels=self.labels_placeholder[:, 1:])

		# First average across timestep
		masked_losses = all_losses*self.mask_placeholder[:, 1:]
		summed_losses = tf.reduce_sum(masked_losses, axis = 1)/tf.reduce_sum(self.mask_placeholder, axis = 1)

		# Then average across example
		self.loss = tf.reduce_mean(summed_losses)

		# Keep track of the change in loss
		tf.summary.scalar("Training Loss", self.loss)


	'''
	function: add_training_op
	-------------------------
	Adds the optimizer that minimizes the loss function.

	TODO: Add global norm computation
	'''
	def add_training_op(self):
		print 'Adding training op'
		params = tf.get_collection(tf.GraphKeys.GLOBAL_VARIABLES)
		for param in params:
			print param
		self.optimizer = tf.train.AdamOptimizer(learning_rate=self.config.lr).minimize(self.loss)
		# optimizer = tf.train.AdamOptimizer(learning_rate=self.config.lr)
		# gvs = optimizer.compute_gradients(self.loss)
		# print gvas
  #       # gs, vs = zip(*gvs)
  #       # # Clip gradients only if self.self.config.clip_gradients is True.
  #       # if self.config.clip_gradients:
  #       #     gs, _ = tf.clip_by_global_norm(gs, self.config.max_grad_norm)
  #       #     gvs = zip(gs, vs)
  #       # # Remember to set self.grad_norm
  #       # self.grad_norm = tf.global_norm(gs)
  #       # tf.summary.scalar("Gradient Norm", self.grad_norm)
  #       self.optimizer = optimizer.apply_gradients(gvas)

    # Merges all summaries
	def add_summary_op(self):
		self.merged_summary_op = tf.summary.merge_all()

	# Trains on a single batch of input data
	def train_on_batch(self, sess, train_inputs, train_seq_len, train_targets, train_mask):
		feed_dict = self.create_feed_dict(inputs=train_inputs, seq_lens=train_seq_len, \
										labels=train_targets, mask=train_mask)
		output_dict = [self.loss, self.optimizer, self.merged_summary_op]
		loss, optimizer, summary = sess.run(output_dict, feed_dict = feed_dict)
		return loss, optimizer, summary

	# Gets loss value on a single batch of input data
	def loss_on_batch(self, sess, inputs, seq_len, targets, mask):
		feed_dict = self.create_feed_dict(inputs=inputs, seq_lens=seq_len, \
										labels=targets, mask=mask)
		output_dict = [self.loss]
		loss = sess.run(output_dict, feed_dict = feed_dict)
		return loss

	# Tests on a single batch of data
	def test_on_batch(self, sess, test_inputs, test_seq_len, test_targets):
		feed_dict = self.create_feed_dict(inputs=test_inputs, seq_lens=test_seq_len,\
										labels=test_targets)
		test_preds = sess.run(self.decoded, feed_dict = feed_dict)
		return None, test_preds


