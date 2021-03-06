'''
Model definition for baseline seq-to-seq model.
'''
import tensorflow as tf
import numpy as np
from tensorflow.python.layers.core import Dense

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

		# Add attention-based cell
		# self.add_cell()

		self.add_output_layer()

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
		self.input_placeholder = tf.placeholder(tf.float32, shape=(self.config.batch_size, None, self.config.num_input_features), name='inputs')
		self.labels_placeholder = tf.placeholder(tf.int32, shape=(self.config.batch_size, self.config.max_out_len + 2), name="target_seq")
		self.input_seq_lens = tf.placeholder(tf.int32, shape=(self.config.batch_size,), name='in_seq_lens')
		self.mask_placeholder = tf.placeholder(tf.float32, shape=(self.config.batch_size, self.config.max_out_len + 2), name="mask")


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
			cell_fw = tf.contrib.rnn.GRUCell(num_units = self.config.encoder_hidden_size)
			cell_bw = tf.contrib.rnn.GRUCell(num_units = self.config.encoder_hidden_size)
			outputs, states = tf.nn.bidirectional_dynamic_rnn(cell_fw = cell_fw, cell_bw = cell_bw, inputs=self.input_placeholder, \
											sequence_length=self.input_seq_lens, dtype=tf.float32)

			# Concatenate the forward and backward final hidden states
			self.encoded = tf.concat(states, 1)
			self.encoded = tf.reshape(self.encoded, [self.config.batch_size, 2*self.config.encoder_hidden_size])	
			# Take concatenenated forward and backward hidden states as memory
			self.memory = tf.concat(outputs, 2)
			print 'Encoded shape', self.encoded
			print 'Memory shape', self.memory.get_shape()

	def add_output_layer(self):
		self.output_layer = Dense(units=self.config.vocab_size, \
								kernel_initializer=tf.contrib.layers.xavier_initializer(), \
								name='fc', use_bias=True)


	def add_cell(self):
		with tf.variable_scope('MyDecoderCell'):
			# Define basic cell of decoder
			cell = tf.contrib.rnn.GRUCell(num_units = self.config.decoder_hidden_size)

			# We will use Luong Attention
			att_mech = tf.contrib.seq2seq.LuongAttention(num_units=self.config.decoder_hidden_size, memory=self.memory, \
									memory_sequence_length = self.input_seq_lens)

			# Construct a wrapper around the attention mechanism + cell
			self.decoder_cell = tf.contrib.seq2seq.AttentionWrapper(cell=cell, attention_mechanism=att_mech, \
									attention_layer_size=self.config.decoder_hidden_size, alignment_history=False)

			# We need to convert the final hidden state of the encoder into something that is compatible
			attn_zero = self.decoder_cell.zero_state(batch_size=self.config.batch_size, dtype=tf.float32)
			
			self.init_state = attn_zero.clone(cell_state=self.encoded)
			print 'Init state is', self.init_state.cell_state.shape

		with tf.variable_scope('MyDecoderCell', reuse=True):
			# Define basic cell of decoder
			cell = tf.contrib.rnn.GRUCell(num_units = self.config.decoder_hidden_size)
			print 'Cell', cell
			tiled_memory = tf.contrib.seq2seq.tile_batch(self.memory, multiplier=self.config.num_beams)
			tiled_init_state = tf.contrib.seq2seq.tile_batch(self.encoded, multiplier=self.config.num_beams) 
			tiled_seq_lens = tf.contrib.seq2seq.tile_batch(self.input_seq_lens, multiplier=self.config.num_beams)

			# We will use Luong Attention
			att_mech = tf.contrib.seq2seq.LuongAttention(num_units=self.config.decoder_hidden_size, memory=tiled_memory, \
									memory_sequence_length = tiled_seq_lens)

			# Construct a wrapper around the attention mechanism + cell
			self.beam_decoder_cell = tf.contrib.seq2seq.AttentionWrapper(cell=cell, attention_mechanism=att_mech, \
									attention_layer_size=self.config.decoder_hidden_size, alignment_history=False)

			# We need to convert the final hidden state of the encoder into something that is compatible
			attn_zero = self.decoder_cell.zero_state(batch_size=self.config.num_beams*self.config.batch_size, dtype=tf.float32)
			
			self.init_beam_state = attn_zero.clone(cell_state=tiled_init_state)
			print 'Init state is', self.init_state.cell_state.shape

		
	def add_decoder(self):
		print 'Adding decoder'
		scope='Decoder'
		with tf.variable_scope(scope):
			# Define basic cell of decoder
			cell = tf.contrib.rnn.GRUCell(num_units = self.config.decoder_hidden_size)

			# We will use Luong Attention
			att_mech = tf.contrib.seq2seq.LuongAttention(num_units=self.config.decoder_hidden_size, memory=self.memory, \
									memory_sequence_length = self.input_seq_lens)

			# Construct a wrapper around the attention mechanism + cell
			self.decoder_cell = tf.contrib.seq2seq.AttentionWrapper(cell=cell, attention_mechanism=att_mech, \
									attention_layer_size=self.config.decoder_hidden_size, alignment_history=False)

			# We need to convert the final hidden state of the encoder into something that is compatible
			attn_zero = self.decoder_cell.zero_state(batch_size=self.config.batch_size, dtype=tf.float32)
			
			self.init_state = attn_zero.clone(cell_state=self.encoded)
			print 'Init state is', self.init_state.cell_state.shape


			# Reshape
			decoder_inputs = tf.nn.embedding_lookup(self.L, ids=self.labels_placeholder)
			decoder_inputs = tf.unstack(decoder_inputs, axis=1)[:-1]
			outputs, _ = tf.contrib.legacy_seq2seq.rnn_decoder(decoder_inputs=decoder_inputs,\
												initial_state = self.init_state,\
												cell=self.decoder_cell, loop_function=None, scope=scope)

			# Convert outputs back into Tensor
			tensor_preds = tf.stack(outputs, axis=1)

			# Compute dot product
			original_shape = tf.shape(tensor_preds)
			outputs_flat = tf.reshape(tensor_preds, [-1, self.config.decoder_hidden_size])
			logits_flat = self.output_layer(outputs_flat)

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



			cell = tf.contrib.rnn.GRUCell(num_units = self.config.decoder_hidden_size)
			print 'Cell', cell
			tiled_memory = tf.contrib.seq2seq.tile_batch(self.memory, multiplier=self.config.num_beams)
			tiled_init_state = tf.contrib.seq2seq.tile_batch(self.encoded, multiplier=self.config.num_beams) 
			tiled_seq_lens = tf.contrib.seq2seq.tile_batch(self.input_seq_lens, multiplier=self.config.num_beams)
			print 'Tiled memory', tiled_memory
			print 'Tiled init state', tiled_init_state
			print 'Tiled seq_lens', tiled_seq_lens
			# We will use Luong Attention
			att_mech = tf.contrib.seq2seq.LuongAttention(num_units=self.config.decoder_hidden_size, memory=tiled_memory, \
									memory_sequence_length = tiled_seq_lens)

			# Construct a wrapper around the attention mechanism + cell
			self.beam_decoder_cell = tf.contrib.seq2seq.AttentionWrapper(cell=cell, attention_mechanism=att_mech, \
									attention_layer_size=self.config.decoder_hidden_size, alignment_history=False)

			# We need to convert the final hidden state of the encoder into something that is compatible
			attn_zero = self.beam_decoder_cell.zero_state(batch_size=self.config.num_beams*self.config.batch_size, dtype=tf.float32)
			
			self.init_beam_state = attn_zero.clone(cell_state=tiled_init_state)

			print 'Init beam state', self.init_beam_state
			first_tokens = self.labels_placeholder[:, 0]
			tiled_first_tokens = tf.contrib.seq2seq.tile_batch(first_tokens, multiplier=self.config.num_beams)
			print 'First tokens', tiled_first_tokens
			beam_search_decoder = tf.contrib.seq2seq.BeamSearchDecoder(cell=self.beam_decoder_cell, embedding=self.L,\
													start_tokens=tiled_first_tokens, \
													end_token=self.config.vocab_size - 1, initial_state=self.init_beam_state,\
													beam_width=self.config.num_beams, output_layer=self.output_layer, length_penalty_weight=0.0)

			final_outputs, final_state, final_sequence_lengths = tf.contrib.seq2seq.dynamic_decode(beam_search_decoder, \
									output_time_major=True, maximum_iterations=self.config.max_out_len)

			print 'Final outputs', final_outputs
			print 'Final state', final_state
			print 'Final Seq. Lens', final_sequence_lengths
			# Use the same cell and output projection as in the decoder train case
			# cell = MyAttCell(memory=self.memory, num_units = self.config.decoder_hidden_size)

			# attn_zero = self.decoder_cell.zero_state(batch_size=tf.shape(self.encoded)[0]*self.config.num_beams, \
			# 			dtype=tf.float32)
			# init_state = attn_zero.clone(cell_state=self.encoded)

			# def output_fn(inputs):
			# 	original_shape = tf.shape(inputs)
			# 	outputs_flat = tf.reshape(inputs, [-1, self.config.decoder_hidden_size])
			# 	logits_flat = tf.matmul(outputs_flat, W) + b
			# 	logits = tf.reshape(logits_flat, [original_shape[0], original_shape[1], self.config.vocab_size])
			# 	return tf.nn.log_softmax(logits)

			# def emb_fn(tokens):
			# 	original_shape = tf.shape(tokens)
			# 	outputs = tf.nn.embedding_lookup(self.L, tokens)
			# 	return tf.reshape(outputs, [original_shape[0], original_shape[1], self.config.embedding_dim])

			# start_tokens = tf.nn.embedding_lookup(self.L, self.labels_placeholder[:, 0])
			# self.decoded, _ = beam_decoder(
			#     cell=self.decoder_cell,
			#     beam_size=self.config.num_beams,
			#     stop_token=config.vocab_size - 1,
			#     initial_state=self.init_state,
			#     initial_input=start_tokens,
			#     tokens_to_inputs_fn=emb_fn,
			#     max_len=self.config.max_out_len,
			#     scope=scope,
			#     outputs_to_score_fn=output_fn,
			#     output_dense=True,
			#     cell_transform='replicate',
			#     score_upper_bound = 0.0
			# )


			# Greedy decoder
			# def loop_fn(prev, i):
			# 	indices = tf.argmax(tf.matmul(prev, W) + b, axis=1)
			# 	return tf.nn.embedding_lookup(self.L, indices)


			# decoder_inputs = tf.nn.embedding_lookup(self.L, ids=self.labels_placeholder)
			# decoder_inputs = tf.unstack(decoder_inputs, axis=1)[:-1]
			# outputs, _ = tf.contrib.legacy_seq2seq.rnn_decoder(decoder_inputs=decoder_inputs,\
			# 									initial_state = self.init_state,\
			# 									cell=self.decoder_cell, loop_function=loop_fn, scope=scope)

			# # Convert back to tensor
			# tensor_preds = tf.stack(outputs, axis=1)

			# # Compute output_projection
			# original_shape = tf.shape(tensor_preds)
			# outputs_flat = tf.reshape(tensor_preds, [-1, self.config.decoder_hidden_size])
			# logits_flat = tf.matmul(outputs_flat, W) + b

			# # Reshape back to original
			# self.test_scores = tf.reshape(logits_flat, [original_shape[0], original_shape[1], self.config.vocab_size])
			# self.greedy_decoded = tf.argmax(self.test_scores, axis=2)



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
		test_preds = sess.run(self.greedy_decoded, feed_dict = feed_dict)
		return None, test_preds

	# Tests on a single batch of data
	def test_greedy_on_batch(self, sess, test_inputs, test_seq_len, test_targets):
		feed_dict = self.create_feed_dict(inputs=test_inputs, seq_lens=test_seq_len,\
										labels=test_targets)
		test_preds = sess.run(self.greedy_decoded, feed_dict = feed_dict)
		return None, test_preds


