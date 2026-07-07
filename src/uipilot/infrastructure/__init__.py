# Infrastructure layer — I/O and external concerns.
#
# The only place that touches YAML, the filesystem, dynamic imports, and pack
# directory layout. Depends inward on the domain; produces/consumes domain
# objects and never imports the application or presentation layers.
#
# Components:
#   pack_loader        load a pack directory (config + YAML) into the domain
#                      model; tolerant of incomplete models so the linter can
#                      report everything at once.
#   capabilities       registry that imports a pack's named auth adapters
#                      (module:function) so they can be listed and binding-checked.
#   markdown_importer  one-shot converter that seeds pack YAML from a retired
#                      Markdown flow map.
